import { createClient } from 'jsr:@supabase/supabase-js@2';

const TG = `https://api.telegram.org/bot${Deno.env.get('BOT_TOKEN')}`;
// کلیدِ گزارشِ هفتگی داخلِ کد نوشته نمی‌شود: اول از متغیرِ محیطی، وگرنه از جدولِ قفل‌شده‌ی app_config
async function cronKey(): Promise<string> {
  const fromEnv = Deno.env.get('CRON_KEY');
  if (fromEnv) return fromEnv;
  try {
    const { data } = await supabase.from('app_config').select('value').eq('key', 'cron_key').maybeSingle();
    return (data && data.value) ? String(data.value) : '';
  } catch (_) { return ''; }
}
const TG_UPLOAD_MAX = 50 * 1024 * 1024;
const PER_PAGE = 20;
const NEW_DAYS = 21;
const MED_BUCKET = 'product-media';
// بسته‌بندیِ فروش: نیم‌جین ۶ عدد و جینِ کامل ۱۲ عدد.
// مشتری می‌تواند چند جین بگیرد، و روی هر تعداد جین یک نیم‌جین هم اضافه کند:
//   ۶ (نیم‌جین) · ۱۲ (یک جین) · ۱۸ (جین‌ونیم) · ۲۴ (دو جین) · ۳۰ (دو جین‌ونیم) …
// یعنی هر مضربِ ۶. کمتر از ۶ نداریم و عددِ غیرِ‌مضرب هم نداریم.
// هم در پیامِ پرسش گفته می‌شود هم در ورودی سد می‌شود — گفتنِ قاعده بدونِ اجرا
// کردنش یعنی سفارشی که نمی‌شود فرستاد و مالک باید زنگ بزند و درستش کند.
// **عدد گرفته می‌شود نه تعدادِ جین** (خواستِ صریحِ مالک)، چون «یک و نیم» هم
// می‌تواند یعنی ۱۸ باشد هم اشتباهِ تایپی — و حدس زدنش سفارشِ غلط می‌سازد.
const PACK_STEP = 6;
function packOk(q: number) { return q > 0 && q % PACK_STEP === 0; }
const PACK_HINT = '📦 نیم‌جین = <b>۶ عدد</b>\n📦 جینِ کامل = <b>۱۲ عدد</b>\n\nچند جین یا جین‌ونیم هم می‌شه: <b>۱۸</b> · <b>۲۴</b> · <b>۳۰</b> · <b>۳۶</b> …\n\n☝️ <b>تعدادِ عدد رو بنویس، نه تعدادِ جین رو</b> — برای یک جین و نیم بنویس <b>۱۸</b>.';
const supabase = createClient(
  Deno.env.get('SUPABASE_URL')!,
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
);

async function tgCall(method: string, payload: any) {
  try {
    // بدونِ مهلت، یک درخواستِ آویزان به تلگرام کلِ فراخوانی را نگه می‌دارد تا
    // خودِ Edge Function کشته شود — و کاربر فقط یک انتظارِ بی‌پایان می‌بیند.
    const r = await fetch(`${TG}/${method}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(25000),
    });
    return await r.json();
  } catch (_) { return { ok: false }; }
}

async function headSize(u: string) {
  try { const r = await fetch(u, { method: 'HEAD' }); return Number(r.headers.get('content-length') || 0); } catch (_) { return 0; }
}

function storagePathOf(u: string) {
  const s = String(u || '').split('/object/public/' + MED_BUCKET + '/');
  return s.length > 1 ? decodeURIComponent(s[1]) : null;
}

async function tgUploadFromUrl(method: string, field: string, fileUrl: string, fileName: string, mime: string, fields: Record<string, string>) {
  let src: Response;
  try { src = await fetch(fileUrl); } catch (_) { return { ok: false }; }
  if (!src.ok || !src.body) return { ok: false };
  const boundary = '----mlq' + Date.now().toString(16) + Math.random().toString(16).slice(2);
  const enc = new TextEncoder();
  let hs = '';
  for (const k of Object.keys(fields)) {
    hs += `--${boundary}\r\nContent-Disposition: form-data; name="${k}"\r\n\r\n${fields[k]}\r\n`;
  }
  hs += `--${boundary}\r\nContent-Disposition: form-data; name="${field}"; filename="${fileName}"\r\nContent-Type: ${mime}\r\n\r\n`;
  const head = enc.encode(hs);
  const tail = enc.encode(`\r\n--${boundary}--\r\n`);
  const reader = src.body.getReader();
  let sentHead = false;
  const stream = new ReadableStream({
    async pull(c) {
      if (!sentHead) { sentHead = true; c.enqueue(head); return; }
      const { done, value } = await reader.read();
      if (done) { c.enqueue(tail); c.close(); return; }
      c.enqueue(value);
    },
    cancel() { try { reader.cancel(); } catch (_) {} },
  });
  try {
    const r = await fetch(`${TG}/${method}`, {
      method: 'POST',
      headers: { 'Content-Type': 'multipart/form-data; boundary=' + boundary },
      body: stream,
      // @ts-expect-error — duplex در تایپِ RequestInitِ Deno نیست، ولی برای
      // بدنه‌ی جریانی لازم است. سرکوبِ کور نه: اگر روزی به تایپ‌ها اضافه شود،
      // expect-error خودش خطا می‌دهد و خبردار می‌شویم (STACK-05).
      duplex: 'half',
    });
    return await r.json();
  } catch (_) { return { ok: false }; }
}

async function send(chatId: number, text: string, keyboard?: any) {
  return await tgCall('sendMessage', { chat_id: chatId, text, parse_mode: 'HTML', reply_markup: keyboard });
}
async function sendPhoto(chatId: number, photo: string, caption: string, keyboard?: any) {
  return await tgCall('sendPhoto', { chat_id: chatId, photo, caption, parse_mode: 'HTML', reply_markup: keyboard });
}
async function answerCallback(id: string) {
  return await tgCall('answerCallbackQuery', { callback_query_id: id });
}

async function getSession(chatId: number) {
  const { data } = await supabase
    .from('telegram_sessions').select('*').eq('chat_id', chatId).maybeSingle();
  if (data) return data;
  const { data: created } = await supabase
    .from('telegram_sessions').insert({ chat_id: chatId, step: 'idle', cart: [] })
    .select().single();
  return created;
}

async function setSession(chatId: number, fields: any) {
  await supabase.from('telegram_sessions')
    .update({ ...fields, updated_at: new Date().toISOString() })
    .eq('chat_id', chatId);
}

/* ── رویدادنگارِ قیفِ فروش (نسخه‌ی ۴۱) ────────────────────────────────────
   پایه‌ی صفحه‌ی «بازدید و نرخِ تبدیل» در پنل. تا امروز از رفتارِ مشتری در ربات
   هیچ ردی نمی‌مانْد: `telegram_sessions` جای هر نفر یک ردیف دارد که سرِ جا
   بازنویسی می‌شود و حتی `created_at` ندارد.

   قاعده‌هایش، هم‌خانواده‌ی `reportError` در پنل — هیچ‌کدام را نشکن:
   ۱ **هرگز throw نکند.** آمار حق ندارد خریدِ مشتری را بخواباند؛ هر خطا فقط
     `warn` می‌شود، چون کسی نباید نصفه‌شب برای یک ردیفِ آمار بیدار شود.
   ۲ **هیچ متنِ پیامِ مشتری نمی‌فرستد** — فقط «کی، چه کاری، روی کدام کالا»
     (SEC-08). `meta` عمداً فقط عدد می‌گیرد.
   ۳ **منتظرش می‌مانیم.** در Supabase Edge هر درخواست ایزوله‌ی خودش را دارد و
     بعد از برگشتنِ پاسخ چیزی زنده نمی‌مانَد، پس promiseی رهاشده ممکن است اصلاً
     اجرا نشود — همان درسِ TEST-10 که سقفِ نرخِ درون‌حافظه‌ای را قلابی کرد.
   ۴ **نامِ رویداد را خودِ دیتابیس با CHECK می‌سنجد.** غلطِ تایپی اینجا بلند خطا
     می‌دهد، نه اینکه یک رویدادِ نامرئی بسازد که هیچ‌جا شمرده نمی‌شود.
   ۵ با نقشِ سرویس می‌رود و RLS نوشتن را به هیچ مشتری‌ای نمی‌دهد، پس آمار
     جعل‌شدنی نیست.

   `rid` نمی‌گیرد و این یک معامله‌ی آگاهانه است: این تابع از شش جای مختلف صدا
   زده می‌شود و رساندنِ شناسه‌ی همبستگی به همه‌شان یعنی عوض کردنِ امضای شش تابع
   روی رباتِ زنده. خطِ شکستش خودش گویاست (نامِ رویداد + پیامِ خطا) و مسیری نیست
   که کسی با همبستگی دنبالش بگردد. */
async function logEvent(chatId: number, event: string, productId?: string | null, meta?: Record<string, number> | null) {
  try {
    const { error } = await supabase.from('bot_events')
      .insert({ chat_id: chatId, event, product_id: productId || null, meta: meta || null });
    if (error) log('evt', 'warn', 'event.insert_failed', { ev: event, msg: String(error.message).slice(0, 120) });
  } catch (e) {
    log('evt', 'warn', 'event.threw', { ev: event, ...errInfo(e) });
  }
}

function fa(n: number) {
  return Math.round(n || 0).toLocaleString('en-US')
    .replace(/[0-9]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[+d]);
}

/* نامِ کالا ممکن است لاتین داشته باشد («دورس تو کرک P&C FLORIDA»). در بندِ
   راست‌به‌چپ، آن تکه‌ی لاتین با عددِ کنارش یک اجرای LTR مشترک می‌سازد و قیمت را از
   تهِ خط می‌کشد کنارِ نام — یعنی مشتری قیمت را جای اشتباه می‌بیند. با مختصات
   اندازه‌گیری شد (نه با متن، چون خودِ رشته درست است):
     بدونِ ایزوله → فارسی ← قیمت ← انگلیسی
     با ایزوله   → فارسی ← انگلیسی ← قیمت
   FSI…PDI نام را یک واحدِ بسته می‌کند و جهتش را از خودش می‌گیرد. */
const bidi = (v: unknown) => '\u2068' + String(v ?? '') + '\u2069';
function escH(s: any) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function agoFa(iso: string) {
  const t = new Date(iso).getTime();
  if (!t) return '';
  const d = Math.floor((Date.now() - t) / 86400000);
  if (d <= 0) return 'امروز';
  if (d === 1) return 'دیروز';
  if (d < 30) return fa(d) + ' روز پیش';
  return fa(Math.floor(d / 30)) + ' ماه پیش';
}

/* ── پرداختِ تکه‌تکه (نسخه‌ی ۴۶) ─────────────────────────────────────────────
   مالک گفت بعضی مشتری‌ها نمی‌توانند کلِ پول را یک‌جا بزنند، پس یک سفارش می‌تواند
   چند کارت داشته باشد. `telegram_orders.cards` آرایه است، به ترتیبِ فرستادن:
     [{fid, amount, at}, …]
   «مانده» هیچ‌جا ذخیره نمی‌شود و همیشه از همین آرایه حساب می‌شود (ARCH-04) —
   عددِ پولی که دو جا نگه داشته شود بالاخره یک روز دو مقدارِ متفاوت می‌شود. */
function cardsOf(o: any): any[] {
  const cs = o && o.cards;
  return Array.isArray(cs) ? cs : [];
}

/* مجموعِ آنچه تا حالا به کارت‌ها تخصیص داده‌ایم — و **`null` اگر خوانده نشود.**
   وسوسه‌ی `|| 0` را نخور: صفر اینجا یک ادعاست و ادعای غلط. مانده را بزرگ‌تر از
   واقعیت نشان می‌دهد، یعنی ربات از مشتری **بیشتر از بدهی‌اش** پول می‌خواهد.
   همان درسی که در پنل از `payFromInvoice` گرفتیم: شکستِ خواندنِ عددِ پول باید
   یک حالتِ سوم بسازد — «نمی‌دانم» — نه اینکه به صفر تا بخورد. */
function assignedOf(o: any): number | null {
  const cs = o && o.cards;
  if (cs == null) return 0;
  if (!Array.isArray(cs)) return null;
  let s = 0;
  for (const c of cs) {
    const a = Number(c && c.amount);
    if (!Number.isFinite(a) || a <= 0) return null;
    s += Math.round(a);
  }
  return s;
}
function remainOf(o: any): number | null {
  const a = assignedOf(o);
  if (a === null) return null;
  return Math.max(0, Math.round(Number(o && o.total) || 0) - a);
}

/* مبلغی که مدیر در کپشنِ عکسِ کارت می‌نویسد.
   رقمِ فارسی و عربی و جداکننده‌ی هزار را می‌فهمد، ولی **حدس نمی‌زند**: هر چیزِ
   دیگری `null` می‌شود تا خودِ مدیر درستش کند (API-07 — در مرز رد کن، ترمیم نکن).
   نقطه عمداً جداکننده حساب نمی‌شود: «۱۲.۵» هم می‌تواند دوازده‌ونیم باشد هم
   دوازده‌هزاروپانصد، و حدس زدنش مبلغِ غلط روی کارتِ مشتری می‌گذارد. */
function parseToman(t: string): number | null {
  const s = String(t ?? '')
    .replace(/[۰-۹]/g, (d: string) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
    .replace(/[٠-٩]/g, (d: string) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)))
    .replace(/[,٬،_\s]/g, '')
    .trim();
  // واحدِ نوشته‌شده حذف می‌شود، **جز ریال**: «۵۰۰۰۰۰۰ ریال» را اگر تومان حساب
  // کنیم ده برابر اشتباه می‌شود، پس اصلاً قبولش نمی‌کنیم و مدیر خودش تصحیح کند.
  const m = /^(\d{1,12})(?:تومان|تومن|ت)?$/.exec(s);
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isFinite(n) && n > 0 ? n : null;
}

const AMOUNT_HINT = 'مبلغ رو با رقم و به <b>تومان</b> بنویس — مثلاً <code>5000000</code> یا <code>۵,۰۰۰,۰۰۰ تومان</code>.';

/* چیزی که مدیر قبل از فرستادنِ عکسِ کارت می‌بیند. سه عدد را با هم می‌گوید —
   جمع، تخصیص‌داده‌شده، مانده — چون خواستِ مالک دقیقاً همین بود: «ربات حساب کنه
   چقد گفتیم واریز کنه و چقد مونده». */
function cardPrompt(ord: any, rem: number) {
  const tot = Math.round(Number(ord.total) || 0);
  const done = tot - rem;
  let t = '📸 <b>عکسِ کارت رو بفرست.</b>\n\n';
  t += `🧾 جمعِ سفارش: <b>${fa(tot)} تومان</b>\n`;
  if (done > 0) t += `✅ تا حالا روی کارت‌ها: ${fa(done)} تومان\n`;
  t += `⏳ مونده: <b>${fa(rem)} تومان</b>\n\n`;
  t += `اگه همه‌ی این ${fa(rem)} تومان به همین کارت می‌ره، فقط عکس رو بفرست.\n`;
  t += `اگه فقط بخشیش به این کارته، <b>مبلغ رو تو کپشنِ همون عکس بنویس</b>. ${AMOUNT_HINT}`;
  return t;
}

/* کارت‌های ثبت‌شده را دوباره برای مشتری می‌فرستد، هرکدام با مبلغِ خودش.
   تکه‌تکه بودن باید روی **هر** عکس نوشته باشد نه فقط در یک پیامِ خلاصه —
   مشتری بعداً که اسکرول می‌کند، همان عکس را می‌بیند نه خلاصه را. */
async function resendCards(chatId: number, ord: any) {
  const list = cardsOf(ord);
  for (let i = 0; i < list.length; i++) {
    const c = list[i];
    const amt = Number(c && c.amount);
    // مبلغِ ناخوانا نباید «۰ تومان» چاپ شود — `fa()` هر چیزِ نامعتبر را صفر
    // می‌کند و صفر اینجا یعنی «چیزی به این کارت نزن»، که ادعای غلطی است.
    const money = Number.isFinite(amt) && amt > 0
      ? `<b>${fa(amt)} تومان</b>` : '<b>(مبلغش خونده نشد — بهمون بگو)</b>';
    const cap = list.length === 1
      ? `💳 مبلغِ ${money} رو به این کارت واریز کن.`
      : `💳 <b>کارتِ ${fa(i + 1)} از ${fa(list.length)}</b> — مبلغِ ${money} به این کارت.`;
    await sendPhoto(chatId, String(c && c.fid), cap);
  }
}

function orderStatusFa(o: any) {
  if (o.status === 'cancelled') return '❌ لغو شده';
  if (o.invoice_id) return '📦 فاکتورش صادر شد';
  if (o.paid_confirmed_at) return '✅ پرداخت تأیید شد';
  if (o.receipt_sent_at) return '🧾 فیشت رسید — در حالِ بررسی';
  if (o.card_sent_at) {
    // کارتِ نصفه با کارتِ کامل یک شکل نباشد، وگرنه مشتری فکر می‌کند تمام شده.
    const r = remainOf(o);
    if (r !== null && r > 0) return `💳 کارت رفت — هنوز ${fa(r)} تومانش کارت نخورده`;
    return '💳 کارت فرستاده شد — منتظرِ فیش';
  }
  return '⏳ ثبت شد — در حالِ هماهنگی';
}

async function notifyAdmins(text: string) {
  const { data: admins } = await supabase.from('bot_admins').select('chat_id');
  for (const a of (admins || [])) { try { await send(Number(a.chat_id), text); } catch (_) {} }
}

async function isAdmin(chatId: number) {
  const { data } = await supabase
    .from('bot_admins').select('chat_id').eq('chat_id', chatId).maybeSingle();
  return !!data;
}

function cleanPhotos(v: any) {
  return Array.isArray(v) ? v.filter((x: any) => x && (x.url || x.fid)) : [];
}

/* `payOrderId` وقتی پر است که مشتری دکمه‌ی «دربارهٔ واریز حرف بزنم» را زده باشد.
   آن‌وقت پیام برای مدیر **سه عدد** را هم با خودش می‌آورد و یک دکمه‌ی «فرستادنِ
   کارت» — وگرنه مدیر باید برود سفارش را پیدا کند و تا آن موقع مشتری رفته. */
async function forwardQuestion(chatId: number, msg: any, text: string, photoId: string | null, payOrderId?: string | null) {
  const s = await getSession(chatId);
  const from = msg && msg.from ? msg.from : {};
  const who = (s && s.customer_name) || from.first_name || from.username || 'مشتری';
  const uname = from.username ? ' (@' + from.username + ')' : '';
  const phone = (s && s.customer_phone) ? '\n📞 ' + escH(s.customer_phone) : '';
  const body = String(text || '').trim();
  let head = '💬 <b>سؤال از مشتری</b>';
  let money = '';
  let payBack: string | null = null;
  const rows: any[] = [[{ text: '✍️ جواب بده', callback_data: 'rp_' + chatId }]];
  if (payOrderId) {
    const { data: po } = await supabase.from('telegram_orders').select('id,total,cards').eq('id', payOrderId).maybeSingle();
    if (po) {
      const rem = remainOf(po);
      head = '💳 <b>مشتری دربارهٔ واریز حرف داره</b>';
      money = `\n🧾 جمعِ سفارش: <b>${fa(po.total)} تومان</b>`
        + (rem === null ? '\n⚠️ مانده خونده نشد' : `\n⏳ مونده: <b>${fa(rem)} تومان</b>`);
      if (rem === null || rem > 0) rows.unshift([{ text: '💳 فرستادنِ کارت به مشتری', callback_data: `sendcard_${po.id}` }]);
      // اگر کارتی رفته، مشتری هنوز وسطِ مسیرِ فیش است.
      if (cardsOf(po).length) payBack = String(po.id);
    }
  }
  const cap = `${head}\n👤 ${escH(who)}${escH(uname)}${phone}${money}\n\n${escH(body || '(بدونِ متن)')}`;
  const kb = { inline_keyboard: rows };
  const { data: admins } = await supabase.from('bot_admins').select('chat_id');
  let sent = 0;
  for (const a of (admins || [])) {
    try {
      const r = photoId ? await sendPhoto(Number(a.chat_id), photoId, cap, kb) : await send(Number(a.chat_id), cap, kb);
      if (r && r.ok) sent++;
    } catch (_) {}
  }
  await setSession(chatId, payBack
    ? { step: 'awaiting_receipt', temp_order_id: payBack }
    : { step: 'idle' });
  if (sent) await send(chatId, payOrderId
    ? '✅ پیامت دربارهٔ واریز رسید دستِ فروشگاه — به‌زودی همین‌جا جوابت رو می‌دیم 🌹'
    : '✅ سؤالت رسید دستِ فروشگاه — به‌زودی همین‌جا جوابت رو می‌دیم 🌹');
  else await send(chatId, 'الان نتونستم پیامت رو برسونم 🙏 یه‌بارِ دیگه امتحان کن.');
}

/* جدول‌هایی که در پشتیبان می‌آیند.
   `employees` از این فهرست **برداشته شد**: چنین جدولی در دیتابیس وجود ندارد و
   سال‌ها بی‌صدا `[]` تولید می‌کرد — خودش شاهدِ این بود که کسی محتوای پشتیبان را
   وارسی نکرده. `bot_admins` **اضافه شد**: اگر گم شود هیچ‌کس نمی‌تواند ربات را
   اداره کند و `/claimadmin` هم عمداً حذف شده، پس تنها راهِ برگشتش دستِ کسی است
   که به خودِ دیتابیس دسترسی دارد.
   `app_config` عمداً **نیست**: کلیدِ cron در آن است و این فایل توی تلگرام
   می‌رود (SEC-01). `bot_events`، `client_errors` و `telegram_sessions` هم نه —
   آمار و تشخیص و حالتِ گذرا هستند، نه دادهٔ کسب‌وکار. */
const BACKUP_TABLES = ['settings','products','customers','invoices','invoice_items','payments','returns','expenses','salaries','shipments','quotes','discount_codes','telegram_orders','bot_admins'];
const BACKUP_FA: Record<string,string> = { products:'کالا', customers:'مشتری', invoices:'فاکتور', invoice_items:'قلمِ فاکتور', payments:'پرداخت', returns:'مرجوعی', expenses:'خرج', salaries:'حقوق', shipments:'بار', quotes:'پیش‌فاکتور', discount_codes:'کدِ تخفیف', telegram_orders:'سفارشِ ربات', bot_admins:'مدیرِ ربات' };

/* **پشتیبانی که نصفه است نباید شبیهِ پشتیبانِ کامل باشد.**
   نسخه‌ی قبلی روی هر خطا `break` می‌زد و `catch` هم خالی بود، پس جدولی که خوانده
   نمی‌شد بی‌صدا `[]` می‌شد. و چون کپشن فقط جدول‌های ناخالی را می‌شمرد، پشتیبانی که
   نصفِ مغازه را جا انداخته بود دقیقاً شبیهِ پشتیبانِ یک هفته‌ی خلوت به نظر می‌رسید.
   این بدترین شکلِ خرابی است: چیزی که فقط روزِ فاجعه معلوم می‌شود (DATA-09).

   حالا هر جدول یکی از این دو حالت را دارد و قاطی‌شان ممکن نیست:
     · موفق  → `out[t]` آرایه است (شاید خالی) و در `_rows` شمرده می‌شود
     · ناموفق → `out[t]` **null** است و نامش در `_failed` می‌آید
   `_ok` هم صریح می‌گوید پشتیبان کامل است یا نه، تا اسکریپتِ بازگردانی مجبور
   نباشد حدس بزند. */
async function buildBackup() {
  const out: any = {
    _saved_at: new Date().toISOString(), _shop: 'مدلند قشم',
    _format: 2, _tables: BACKUP_TABLES.slice(), _rows: {} as Record<string, number>,
    _failed: [] as string[], _ok: true,
  };
  for (const t of BACKUP_TABLES) {
    const rows: any[] = [];
    let bad = '';
    try {
      let from = 0;
      while (true) {
        const { data, error } = await supabase.from(t).select('*').range(from, from + 999);
        if (error) { bad = String(error.message || 'خطا').slice(0, 120); break; }
        if (!data) { bad = 'پاسخِ خالی'; break; }
        rows.push(...data);
        if (data.length < 1000) break;
        from += 1000;
      }
    } catch (e) { bad = (e instanceof Error ? e.message : String(e)).slice(0, 120); }
    if (bad) {
      out[t] = null;
      out._failed.push(t);
      out._ok = false;
      log('backup', 'error', 'backup.table_failed', { table: t, msg: bad });
    } else {
      out[t] = rows;
      out._rows[t] = rows.length;
    }
  }
  return out;
}

async function sendBackup(chatId: number) {
  const data = await buildBackup();
  const json = JSON.stringify(data);
  const parts: string[] = [];
  for (const t of BACKUP_TABLES) {
    if (!BACKUP_FA[t]) continue;
    const n = Array.isArray(data[t]) ? data[t].length : 0;
    if (n > 0) parts.push(`${BACKUP_FA[t]}: ${fa(n)}`);
  }
  const kb = Math.max(1, Math.round(new TextEncoder().encode(json).length / 1024));
  const name = 'modland-backup-' + new Date().toISOString().slice(0, 10) + '.json';
  const failed: string[] = Array.isArray(data._failed) ? data._failed : [];
  const cap = failed.length
    ? `⚠️ <b>پشتیبان ناقص گرفته شد — نگهش ندار</b>\n\nاین جدول‌ها خونده نشدن: <b>${failed.map((t: string) => escH(BACKUP_FA[t] || t)).join('، ')}</b>\n\n${parts.length ? parts.join(' · ') : 'هیچ جدولی خونده نشد'}\n\n<b>به این فایل تکیه نکن.</b> یه بارِ دیگه /پشتیبان بزن؛ اگه باز هم همین شد یعنی مشکل از دیتابیسه.`
    : `💾 <b>پشتیبانِ کاملِ مدلند قشم</b>\n${parts.length ? parts.join(' · ') : 'فعلاً داده‌ای ثبت نشده'}\n\nاین فایل همه‌چیزه: کالاها، مشتریا، فاکتورا، پرداختا و تنظیمات (${fa(kb)} کیلوبایت).\n📌 یه جای امن نگهش دار.`;
  const fd = new FormData();
  fd.append('chat_id', String(chatId));
  fd.append('caption', cap);
  fd.append('parse_mode', 'HTML');
  fd.append('document', new Blob([json], { type: 'application/json' }), name);
  try {
    const r = await fetch(`${TG}/sendDocument`, { method: 'POST', body: fd });
    return await r.json();
  } catch (_) { return { ok: false }; }
}

async function deliverVideo(chatId: number, p: any, urlCol: string, fidCol: string, cap: string, quiet?: boolean) {
  const fid = p[fidCol], vurl = p[urlCol];
  if (fid) {
    const r = await tgCall('sendVideo', { chat_id: chatId, video: fid, caption: cap, parse_mode: 'HTML', supports_streaming: true, disable_notification: !!quiet });
    if (r && r.ok) return { st: 'ok', res: r, fid };
  }
  if (!vurl) return { st: 'none' };
  const size = await headSize(vurl);
  if (size > TG_UPLOAD_MAX) return { st: 'too_big', size };
  const isWebm = /\.webm(\?|$)/i.test(vurl);
  const fields: Record<string, string> = { chat_id: String(chatId), supports_streaming: 'true' };
  if (cap) { fields.caption = cap; fields.parse_mode = 'HTML'; }
  if (quiet) fields.disable_notification = 'true';
  const r2 = await tgUploadFromUrl('sendVideo', 'video', vurl, isWebm ? 'v.webm' : 'v.mp4', isWebm ? 'video/webm' : 'video/mp4', fields);
  if (r2 && r2.ok) {
    const nf = r2.result && r2.result.video && r2.result.video.file_id;
    if (nf) {
      const upd: any = {}; upd[fidCol] = nf; upd[urlCol] = null;
      try { await supabase.from('products').update(upd).eq('id', p.id); } catch (_) {}
      const path = storagePathOf(vurl);
      if (path) { try { await supabase.storage.from(MED_BUCKET).remove([path]); } catch (_) {} }
      p[fidCol] = nf; p[urlCol] = null;
    }
    return { st: 'ok', res: r2, fid: nf };
  }
  return { st: 'failed', size };
}

async function sendProductVideo(chatId: number, pid: string, which: 'jin' | 'carton') {
  const urlCol = which === 'jin' ? 'video_jin_url' : 'video_carton_url';
  const fidCol = which === 'jin' ? 'video_jin_fid' : 'video_carton_fid';
  const label = which === 'jin' ? '🎬 فیلمِ جینِ' : '📦 فیلمِ کارتنِ';
  const { data: p } = await supabase.from('products')
    .select(`id,name,${urlCol},${fidCol}`).eq('id', pid).maybeSingle();
  if (!p) { await send(chatId, 'این کالا پیدا نشد 🙏'); return; }
  if (!(p as any)[fidCol] && !(p as any)[urlCol]) { await send(chatId, 'این فیلم هنوز برای این کالا گذاشته نشده 🙏'); return; }
  const cap = `${label} «${escH(p.name)}»`;
  let wait: any = null;
  if (!(p as any)[fidCol]) wait = await send(chatId, '⏳ دارم فیلم رو آماده می‌کنم، چند لحظه صبر کن…');
  const out = await deliverVideo(chatId, p, urlCol, fidCol, cap);
  if (wait && wait.ok && wait.result) { try { await tgCall('deleteMessage', { chat_id: chatId, message_id: wait.result.message_id }); } catch (_) {} }
  if (out.st === 'too_big' || out.st === 'failed') {
    await send(chatId, `${cap}\nحجمش برای تلگرام زیاده — از این لینک ببینش 👇\n${(p as any)[urlCol] || ''}`);
  }
}

async function sendProductPhotos(chatId: number, pid: string) {
  const { data: p } = await supabase.from('products').select('id,name,photos').eq('id', pid).maybeSingle();
  if (!p) { await send(chatId, 'این کالا پیدا نشد 🙏'); return; }
  const photos = cleanPhotos(p.photos);
  if (!photos.length) { await send(chatId, '👗 عکسِ تن‌خور برای این کالا گذاشته نشده 🙏'); return; }
  const cap = `👗 تن‌خورِ «${escH(p.name)}»`;
  if (photos.length === 1) {
    const r = await sendPhoto(chatId, photos[0].fid || photos[0].url, cap);
    if (r && r.ok) {
      const ph = r.result && r.result.photo;
      const nf = ph && ph.length ? ph[ph.length - 1].file_id : null;
      if (nf && nf !== photos[0].fid) {
        const arr = photos.slice(); arr[0] = { ...arr[0], fid: nf };
        try { await supabase.from('products').update({ photos: arr }).eq('id', p.id); } catch (_) {}
      }
    } else { await send(chatId, 'الان نتونستم عکس رو بفرستم 🙏 یه‌بارِ دیگه بزن.'); }
    return;
  }
  const media = photos.slice(0, 10).map((x: any, i: number) => (
    i === 0 ? { type: 'photo', media: x.fid || x.url, caption: cap, parse_mode: 'HTML' }
            : { type: 'photo', media: x.fid || x.url }
  ));
  const r = await tgCall('sendMediaGroup', { chat_id: chatId, media });
  if (r && r.ok && Array.isArray(r.result)) {
    const arr = photos.slice(); let changed = false;
    r.result.forEach((m: any, i: number) => {
      const ph = m && m.photo;
      const nf = ph && ph.length ? ph[ph.length - 1].file_id : null;
      if (nf && arr[i] && arr[i].fid !== nf) { arr[i] = { ...arr[i], fid: nf }; changed = true; }
    });
    if (changed) { try { await supabase.from('products').update({ photos: arr }).eq('id', p.id); } catch (_) {} }
  } else {
    await send(chatId, 'الان نتونستم عکسا رو بفرستم 🙏 یه‌بارِ دیگه بزن.');
  }
}

async function showMyOrders(chatId: number) {
  const { data: rows } = await supabase.from('telegram_orders')
    .select('id,total,items,created_at,status,invoice_id,paid_confirmed_at,receipt_sent_at,card_sent_at,cards')
    .eq('tg_user_id', chatId).order('created_at', { ascending: false }).limit(5);
  const list = rows || [];
  if (!list.length) { await send(chatId, 'هنوز سفارشی ثبت نکردی 🙂'); await showMain(chatId); return; }
  let t = '📋 <b>سفارش‌های تو</b>';
  const kb: any = [];
  for (const o of list) {
    const n = Array.isArray(o.items) ? o.items.length : 0;
    t += `\n\n━━━━━\n🗓 ${agoFa(o.created_at)} · ${fa(n)} قلم\n💰 ${fa(o.total)} تومان\n${orderStatusFa(o)}`;
    if (o.status !== 'cancelled' && !o.paid_confirmed_at && !o.invoice_id) {
      kb.push([{ text: `💳 پرداختِ ${fa(o.total)} ت`, callback_data: `paynow_${o.id}` }]);
    }
  }
  kb.push([{ text: '💬 سؤال دارم', callback_data: 'ask' }]);
  kb.push([{ text: '🛒 سفارشِ جدید', callback_data: 'new_order' }]);
  await send(chatId, t, { inline_keyboard: kb });
}

async function showMain(chatId: number) {
  await setSession(chatId, { step: 'idle', editing_order_id: null });
  const kb: any = [[{ text: '🛒 ثبتِ سفارشِ جدید', callback_data: 'new_order' }]];
  try {
    const { data: last } = await supabase.from('telegram_orders').select('id').eq('tg_user_id', chatId).order('created_at', { ascending: false }).limit(1).maybeSingle();
    if (last) {
      kb.push([{ text: '🔁 همون سفارشِ قبلی', callback_data: 'repeat_last' }]);
      kb.push([{ text: '📋 سفارش‌های من', callback_data: 'myorders' }]);
    }
  } catch (_) {}
  kb.push([{ text: '💬 سؤال دارم', callback_data: 'ask' }]);
  await send(chatId, 'به فروشگاهِ <b>مدلند قشم</b> خوش اومدی 🌟\nبرای ثبتِ سفارش دکمه رو بزن:', { inline_keyboard: kb });
}

function isNewProd(p: any) {
  const t = new Date(p.created_at).getTime();
  return !!t && (Date.now() - t) < NEW_DAYS * 86400000;
}

async function showProducts(chatId: number) {
  await showCategory(chatId, -1, 0);
}

async function showCategory(chatId: number, idx: number, page: number) {
  await setSession(chatId, { step: 'choosing' });
  await logEvent(chatId, 'browse', null, { page: Number(page) || 0 });
  const { data: all } = await supabase.from('products').select('id,name,price,created_at').order('name');
  const products = all || [];
  const isNew = (idx === -2);
  let list = products;
  let title = 'کالا رو انتخاب کن، یا اسمِ جنس رو تایپ کن 🔎';
  if (isNew) {
    list = products.filter(isNewProd).sort((a: any, b: any) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    title = '🆕 <b>تازه‌رسیده‌ها</b> — جنسایی که تازه اضافه شدن:';
  }
  const pages = Math.max(1, Math.ceil(list.length / PER_PAGE));
  if (!(page >= 0)) page = 0;
  if (page > pages - 1) page = pages - 1;
  const slice = list.slice(page * PER_PAGE, page * PER_PAGE + PER_PAGE);
  const btns: any = [];
  for (const p of slice) btns.push([{ text: `${isNew ? '🆕 ' : ''}${bidi(p.name)} — ${fa(p.price)} ت`, callback_data: `p_${p.id}` }]);
  if (pages > 1) {
    const nav: any = [];
    if (page > 0) nav.push({ text: '‹ قبلی', callback_data: `pg_${idx}_${page - 1}` });
    nav.push({ text: `صفحهٔ ${fa(page + 1)} از ${fa(pages)}`, callback_data: 'noop' });
    if (page < pages - 1) nav.push({ text: 'بعدی ›', callback_data: `pg_${idx}_${page + 1}` });
    btns.push(nav);
  }
  if (isNew) {
    btns.push([{ text: '📋 همه‌ی کالاها', callback_data: 'catall' }]);
  } else {
    const newCount = products.filter(isNewProd).length;
    if (newCount) btns.push([{ text: `🆕 جدیدترین‌ها (${fa(newCount)})`, callback_data: 'catnew' }]);
  }
  btns.push([{ text: '💬 سؤال دارم', callback_data: 'ask' }, { text: '✅ تمومِ خرید', callback_data: 'done_items' }]);
  const head = !list.length
    ? (isNew ? 'فعلاً جنسِ تازه‌ای نیست 🙏' : 'فعلاً کالایی ثبت نشده. بعداً دوباره امتحان کن 🙏')
    : (pages > 1 ? `${title}\n(${fa(list.length)} تا کالا)` : title);
  await send(chatId, head, { inline_keyboard: btns });
}

async function showProductDetail(chatId: number, pid: string) {
  const { data: p } = await supabase.from('products')
    .select('id,name,price,size_info,photos,video_jin_url,video_jin_fid,video_carton_url,video_carton_fid')
    .eq('id', pid).maybeSingle();
  if (!p) { await send(chatId, 'این کالا پیدا نشد 🙏'); await showProducts(chatId); return; }
  await setSession(chatId, { temp_product_id: pid });
  await logEvent(chatId, 'view', p.id);
  const photos = cleanPhotos(p.photos);
  const hasJin = !!(p.video_jin_url || p.video_jin_fid);
  const hasCarton = !!(p.video_carton_url || p.video_carton_fid);
  const hasSize = !!(p.size_info && String(p.size_info).trim());
  const txt = `<b>${escH(p.name)}</b>\n💰 قیمت: ${fa(p.price)} تومان`;
  const rows: any[] = [];
  const r1: any[] = [];
  if (hasJin) r1.push({ text: '🎬 فیلمِ جین', callback_data: `jin_${p.id}` });
  if (hasCarton) r1.push({ text: '📦 فیلمِ کارتن', callback_data: `crt_${p.id}` });
  if (r1.length) rows.push(r1);
  const r2: any[] = [];
  if (photos.length) r2.push({ text: `👗 عکسِ تن‌خور${photos.length > 1 ? ' (' + fa(photos.length) + ')' : ''}`, callback_data: `pics_${p.id}` });
  if (hasSize) r2.push({ text: '📏 اندازه و قواره', callback_data: `size_${p.id}` });
  if (r2.length) rows.push(r2);
  rows.push([{ text: '🛒 می‌خوامش', callback_data: `buy_${p.id}` }, { text: '💬 سؤال', callback_data: 'ask' }]);
  rows.push([{ text: '⬅️ برگشت به لیست', callback_data: 'back_list' }]);
  const kb = { inline_keyboard: rows };
  if (photos.length) {
    const r = await sendPhoto(chatId, photos[0].fid || photos[0].url, txt, kb);
    if (r && r.ok) {
      const ph = r.result && r.result.photo;
      const nf = ph && ph.length ? ph[ph.length - 1].file_id : null;
      if (nf && nf !== photos[0].fid) {
        const arr = photos.slice(); arr[0] = { ...arr[0], fid: nf };
        try { await supabase.from('products').update({ photos: arr }).eq('id', p.id); } catch (_) {}
      }
      return;
    }
  }
  await send(chatId, txt, kb);
}

async function showEditCart(chatId: number, extra?: string) {
  const s = await getSession(chatId);
  const cart = (s && s.cart) || [];
  let tot = 0; for (const it of cart) tot += Number(it.quantity || 0) * Number(it.unit_price || 0);
  const kb: any = [];
  cart.forEach((it: any, i: number) => kb.push([{ text: `❌ ${bidi(it.name)} × ${fa(it.quantity)} — ${fa(it.quantity * it.unit_price)} ت`, callback_data: `edel_${i}` }]));
  kb.push([{ text: '➕ افزودنِ جنس', callback_data: 'edadd' }]);
  if (cart.length) kb.push([{ text: '✅ ثبتِ تغییرات', callback_data: 'edok' }]);
  kb.push([{ text: '↩️ بی‌خیالِ ویرایش', callback_data: 'edcancel' }]);
  let t = '✏️ <b>ویرایشِ سفارش</b>\nبرای حذفِ هر قلم، روش بزن:';
  t += cart.length ? `\n\n<b>جمعِ فعلی: ${fa(tot)} تومان</b>` : '\n\nسبد خالیه — یه جنس اضافه کن یا بی‌خیالِ ویرایش شو.';
  if (extra) t += extra;
  await send(chatId, t, { inline_keyboard: kb });
}

async function finalizeOrder(chatId: number, s: any, addressText: string, tgUser: any) {
  const cart = s.cart || [];
  if (!cart.length) { await send(chatId, 'سبدت خالیه 🙂'); await showProducts(chatId); return; }
  const raw = cart.reduce((sum: number, it: any) => sum + it.quantity * it.unit_price, 0);
  const dpct = Number(s.discount_pct || 0);
  const total = dpct > 0 ? Math.max(0, Math.round(raw * (1 - dpct / 100))) : raw;
  const dnote = (dpct > 0 && s.discount_code) ? `کدِ تخفیف ${s.discount_code} (${dpct}٪)` : null;
  const { data: newOrder, error: insErr } = await supabase.from('telegram_orders').insert({ status: 'new', customer_name: s.customer_name, customer_phone: s.customer_phone, customer_city: s.customer_city, customer_address: addressText, tg_user_id: chatId, tg_username: tgUser, items: cart, total, note: dnote }).select('id').single();
  if (insErr || !newOrder) { await setSession(chatId, { step: 'address' }); await send(chatId, 'ثبتِ سفارش خطا خورد 🙏 لطفاً آدرست رو یه بارِ دیگه بفرست.'); return; }
  await logEvent(chatId, 'order', null, { total, items: cart.length });
  let summary = '✅ سفارشت ثبت شد! ممنون 🌹\n\n<b>خلاصه‌ی سفارش:</b>\n';
  for (const it of cart) summary += `• ${bidi(escH(it.name))} × ${fa(it.quantity)} = ${fa(it.quantity * it.unit_price)} ت\n`;
  if (dpct > 0) summary += `\nتخفیف با کدِ ${escH(s.discount_code)}: ${fa(dpct)}٪ (از ${fa(raw)})`;
  summary += `\n<b>جمعِ کل: ${fa(total)} تومان</b>\n\nهر وقت خواستی پرداخت کنی دکمه‌ی زیر رو بزن 👇`;
  await setSession(chatId, { step: 'idle', cart: [] });
  await send(chatId, summary, { inline_keyboard: [[{ text: '💳 می‌خوام پرداخت کنم', callback_data: `paynow_${newOrder.id}` }], [{ text: '✏️ ویرایشِ سفارش', callback_data: `edit_${newOrder.id}` }]] });
  try {
    const { data: admins } = await supabase.from('bot_admins').select('chat_id');
    if (admins && admins.length) {
      let am = `🔔 <b>سفارشِ جدید از ربات</b>\n👤 ${escH(s.customer_name)}\n📞 ${escH(s.customer_phone)}\n🏙 ${escH(s.customer_city)}\n📍 ${escH(addressText)}\n\n`;
      for (const it of cart) am += `• ${bidi(escH(it.name))} × ${fa(it.quantity)} = ${fa(it.quantity * it.unit_price)} ت\n`;
      if (dpct > 0) am += `\nتخفیف: کدِ ${escH(s.discount_code)} ${fa(dpct)}٪ (از ${fa(raw)})`;
      am += `\n<b>جمعِ کل: ${fa(total)} تومان</b>`;
      for (const a of admins) await send(Number(a.chat_id), am, { inline_keyboard: [[{ text: '💳 فرستادنِ کارت به مشتری', callback_data: `sendcard_${newOrder.id}` }]] });
    }
  } catch (_) {}
}

async function buildWeeklyReport() {
  const since = new Date(Date.now() - 7 * 86400000).toISOString();
  const { data: inv } = await supabase.from('invoices').select('id,total_amount,status,created_at').gte('created_at', since);
  const list = inv || [];
  const cancelled = new Set(list.filter((v: any) => v.status === 'cancelled').map((v: any) => v.id));
  const valid = list.filter((v: any) => v.status !== 'cancelled');
  const rev = valid.reduce((s: number, v: any) => s + Number(v.total_amount || 0), 0);
  const { data: its } = await supabase.from('invoice_items').select('product_name,quantity,invoice_id,created_at').gte('created_at', since);
  const pm: any = {};
  for (const it of (its || [])) { if (cancelled.has(it.invoice_id)) continue; const k = it.product_name || 'کالا'; pm[k] = (pm[k] || 0) + Number(it.quantity || 0); }
  const top = Object.entries(pm).sort((a: any, b: any) => b[1] - a[1]).slice(0, 3);
  const { data: bals } = await supabase.from('customer_balances').select('balance');
  const debt = (bals || []).reduce((s: number, b: any) => s + Math.max(0, Number(b.balance || 0)), 0);
  let t = `📊 <b>گزارشِ هفتگیِ مدلند قشم</b>\n🗓 ۷ روزِ اخیر\n\n🧾 فاکتورها: ${fa(valid.length)}\n💰 فروش: ${fa(rev)} ت\n✋ کل طلب از مشتریا: ${fa(debt)} ت\n`;
  if (top.length) { t += `\n🔥 <b>پرفروش‌ها:</b>\n`; top.forEach((e: any, i: number) => { t += `${fa(i + 1)}. ${escH(e[0])} — ${fa(e[1])} عدد\n`; }); }
  if (!valid.length) t += `\nاین هفته فاکتوری ثبت نشده.`;

  /* قیفِ ربات — همان چیزی که صفحه‌ی «بازدید و نرخِ تبدیل» نشان می‌دهد، ولی
     هفته‌ای یک بار خودش می‌آید. فروش تنها نصفِ ماجراست: «۳ فاکتور» بدونِ
     «از ۴۰ نفر» معلوم نمی‌کند هفته‌ی خوبی بوده یا بد.

     از **نما** خوانده می‌شود نه جدول، تا گشت‌وگذارِ خودِ مالک بازدیدکننده
     شمرده نشود. `bot_carts_open` هم فقط سبدهای بازِ همین لحظه است، نه هفته —
     و همین درست است، چون کاری که می‌شود کرد همین الان است.

     اگر خواندن شکست بخورد **هیچ عددی نمی‌آید**، نه صفر: «۰ بازدیدکننده» یعنی
     «هیچ‌کس نیامد» و آن ادعای غلطی است. */
  try {
    const { data: ev, error: evErr } = await supabase
      .from('bot_events_public').select('chat_id,event').gte('created_at', since);
    if (evErr) throw new Error(evErr.message);
    const rows = ev || [];
    if (rows.length) {
      const seen = new Set<string>(), bought = new Set<string>(), carted = new Set<string>();
      for (const r of rows) {
        const c = String(r.chat_id);
        seen.add(c);
        if (r.event === 'order') bought.add(c);
        if (r.event === 'cart_add') carted.add(c);
      }
      // `fa()` خودش گرد می‌کند، پس نرخِ اعشاری بی‌صدا بریده می‌شد. اینجا صریح
      // گرد می‌شود تا کد همان چیزی را بگوید که نشان می‌دهد — در پیامِ تلگرام
      // «۳۳٪» به‌اندازه‌ی کافی گویاست و رقمِ اعشار چیزی اضافه نمی‌کند.
      const conv = seen.size ? Math.round(bought.size * 100 / seen.size) : 0;
      t += `\n\n🌐 <b>ربات این هفته</b>\n👤 بازدیدکننده: ${fa(seen.size)}\n🛒 سبد پر کردن: ${fa(carted.size)}\n✅ سفارش دادن: ${fa(bought.size)}\n📈 نرخِ تبدیل: ${fa(conv)}٪`;
    } else {
      t += `\n\n🌐 <b>ربات این هفته</b>\nاین هفته کسی سراغِ ربات نیومد.`;
    }
    const { data: carts, error: cErr } = await supabase
      .from('bot_carts_open').select('cart_total');
    if (cErr) throw new Error(cErr.message);
    const open = carts || [];
    if (open.length) {
      const sum = open.reduce((s: number, c: any) => s + Number(c.cart_total || 0), 0);
      t += `\n\n🧺 <b>سبدِ رهاشده:</b> ${fa(open.length)} نفر — ${fa(sum)} ت روش مونده\nتو پنل می‌تونی براشون پیام بفرستی.`;
    }
  } catch (e) {
    log('cron', 'warn', 'weekly.funnel_failed', errInfo(e));
    t += `\n\n🌐 آمارِ ربات این هفته خونده نشد — تو پنل ببینش.`;
  }
  return t;
}

// ── نشانیِ امضاشده برای ویدیوی کالا (SEC-02، SEC-03) ────────────────────────
// `?media=` نمی‌تواند هدرِ Authorization بگیرد چون پنل آن را در `<video src>`
// می‌گذارد. پس به‌جای هدر، یک ژتونِ کوتاه‌عمر در خودِ نشانی می‌نشیند.
//
// چرا نه سقفِ نرخِ درون‌حافظه‌ای: اندازه گرفته شد که هر درخواست یک ایزوله‌ی تازه
// می‌گیرد (۱۴ درخواست، ۱۴ شناسه‌ی متفاوت)، پس هیچ شمارنده‌ای بینِ درخواست‌ها
// زنده نمی‌مانَد. آن راه یک محافظِ قلابی بود.
//
// کلید از BOT_TOKEN مشتق می‌شود با برچسبِ جدا (جداسازیِ کلید)، نه خودِ BOT_TOKEN،
// تا امضای ویدیو و احرازِ وبهوک دو چیزِ مستقل بمانند. خودِ ژتون هیچ‌وقت رمز نیست:
// فقط برای همین کالا و همین نوع و تا همان ثانیه معتبر است.
const MED_TTL = 3600; // ثانیه
let _medKey: CryptoKey | null = null;
async function medKey(): Promise<CryptoKey> {
  if (_medKey) return _medKey;
  const seed = new TextEncoder().encode((Deno.env.get('BOT_TOKEN') || '') + '|media-url-v1');
  const raw = await crypto.subtle.digest('SHA-256', seed);
  _medKey = await crypto.subtle.importKey('raw', raw, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return _medKey;
}
async function medSign(pid: string, which: string, exp: number): Promise<string> {
  const k = await medKey();
  const s = await crypto.subtle.sign('HMAC', k, new TextEncoder().encode(`${pid}|${which}|${exp}`));
  const hex = Array.from(new Uint8Array(s)).map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${exp}.${hex.slice(0, 32)}`;
}
async function medCheck(pid: string, which: string, tok: string): Promise<boolean> {
  const dot = tok.indexOf('.');
  if (dot < 1) return false;
  const exp = Number(tok.slice(0, dot));
  if (!Number.isFinite(exp) || exp * 1000 < Date.now()) return false;
  const want = await medSign(pid, which, exp);
  // مقایسه‌ی زمان‌ثابت — مقایسه‌ی معمولی طولِ پیشوندِ درست را لو می‌دهد.
  if (want.length !== tok.length) return false;
  let diff = 0;
  for (let i = 0; i < want.length; i++) diff |= want.charCodeAt(i) ^ tok.charCodeAt(i);
  return diff === 0;
}

// نسخه‌ی این فایل. بازرسِ سرور آن را با عددی که در bot/README.md ثبت شده مقابله
// می‌کند، پس دیگر نمی‌شود مستقر کرد و یادت برود مستند را جلو ببری.
const BOT_VER = 47;

// ── لاگِ ساخت‌یافته (OPS-01، OPS-02) ────────────────────────────────────────
// لاگِ متنیِ آزاد در سوپابیس قابلِ جست‌وجو نیست: نمی‌شود پرسید «این درخواست چه بر
// سرش آمد؟». هر خط یک JSON است با یک شناسه‌ی همبستگی که از ابتدای درخواست تا ته
// زنجیره می‌آید. سه سطح بس است (OPS-02): error یعنی کسی باید ببیند، warn یعنی
// بررسی شود، info رویدادِ کسب‌وکار.
//
// **هیچ داده‌ی مشتری و هیچ رمزی اینجا نمی‌رود** (SEC-08) — فقط نوعِ خطا و
// دویست نویسه‌ی اولِ پیامش.
type LogLevel = 'error' | 'warn' | 'info';
function log(rid: string, level: LogLevel, event: string, extra?: Record<string, unknown>) {
  const line = JSON.stringify({ t: new Date().toISOString(), level, rid, event, ...(extra || {}) });
  if (level === 'error') console.error(line); else console.log(line);
}
function errInfo(e: unknown): Record<string, unknown> {
  if (e instanceof Error) return { err: e.name, msg: String(e.message).slice(0, 200) };
  return { err: 'unknown', msg: String(e).slice(0, 200) };
}

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const rid = crypto.randomUUID().slice(0, 8);

  // درگاهِ سوپابیس به OPTIONS فقط allow-origin می‌دهد و allow-headers نمی‌دهد،
  // پس هر درخواستِ میان‌دامنه‌ای که Authorization دارد در preflight رد می‌شد —
  // و همین یک بار آماده‌سازیِ فیلم را روی تولید شکست.
  if (req.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'authorization, content-type, range',
      'Access-Control-Max-Age': '86400',
    } });
  }

  // صدورِ ژتون: با توکنِ کاربر احراز می‌شود، دقیقاً مثلِ ?prime=.
  const mtok = url.searchParams.get('mediatoken');
  if (mtok) {
    const hdr = { 'Access-Control-Allow-Origin': '*', 'Content-Type': 'application/json' };
    const jwt = (req.headers.get('authorization') || '').replace(/^Bearer\s+/i, '');
    let authed = false;
    if (jwt) {
      try { const u = await supabase.auth.getUser(jwt); authed = !!(u && u.data && u.data.user); }
      catch (e) { log(rid, 'warn', 'mediatoken.auth_failed', errInfo(e)); }
    }
    if (!authed) {
      return new Response(JSON.stringify({ ok: false, error: 'unauthorized' }), { status: 401, headers: hdr });
    }
    const w = url.searchParams.get('which') === 'carton' ? 'carton' : 'jin';
    const exp = Math.floor(Date.now() / 1000) + MED_TTL;
    return new Response(JSON.stringify({ ok: true, tok: await medSign(mtok, w, exp) }), { headers: hdr });
  }

  // ── مسیرِ سلامت (OPS-04) ─────────────────────────────────────────────────
  // «۲۰۰ برمی‌گردانم پس سالمم» چیزی را ثابت نمی‌کند. این یکی واقعاً به دیتابیس
  // می‌زند و اگر نرسد ۵۰۳ می‌دهد — رباتِ بی‌دیتابیس نمی‌تواند سفارش بگیرد، حتی
  // اگر خودش بالا باشد. پشتِ همان کلیدِ cron است تا مسیرِ بی‌احرازِ تازه نسازیم.
  const health = url.searchParams.get('health');
  if (health) {
    const key = await cronKey();
    if (!key || health !== key) {
      log(rid, 'warn', 'health.denied');
      return new Response('no', { status: 401 });
    }
    const t0 = Date.now();
    let db = false;
    try {
      const { error } = await supabase.from('bot_admins').select('chat_id').limit(1);
      db = !error;
      if (error) log(rid, 'error', 'health.db_error', { msg: String(error.message).slice(0, 200) });
    } catch (e) { log(rid, 'error', 'health.db_threw', errInfo(e)); }
    const ms = Date.now() - t0;
    log(rid, db ? 'info' : 'error', 'health', { db, db_ms: ms, ver: BOT_VER });
    return new Response(JSON.stringify({ ok: db, db, db_ms: ms, ver: BOT_VER }),
      { status: db ? 200 : 503, headers: { 'Content-Type': 'application/json' } });
  }

  const media = url.searchParams.get('media');
  if (media) {
    const cors: Record<string, string> = { 'Access-Control-Allow-Origin': '*' };
    const which = url.searchParams.get('which') === 'carton' ? 'carton' : 'jin';
    const fidCol = which === 'jin' ? 'video_jin_fid' : 'video_carton_fid';
    // در بسته است: بی‌ژتون هم رد می‌شود. گامِ «افزودن» (پذیرفتنِ نبودِ ژتون) تا وقتی
    // ماند که مالک تأیید کرد پنلِ گوشی به‌روز شده و فیلم با ژتون باز می‌شود.
    const mt = url.searchParams.get('t');
    if (!mt || !(await medCheck(media, which, mt))) {
      return new Response('bad token', { status: 401, headers: cors });
    }
    try {
      const { data: p } = await supabase.from('products').select(`id,${fidCol}`).eq('id', media).maybeSingle();
      const fid = p ? (p as any)[fidCol] : null;
      if (!fid) return new Response('none', { status: 404, headers: cors });
      const gf = await tgCall('getFile', { file_id: fid });
      if (!gf || !gf.ok || !gf.result || !gf.result.file_path) {
        return new Response('toobig', { status: 413, headers: cors });
      }
      const fileUrl = `https://api.telegram.org/file/bot${Deno.env.get('BOT_TOKEN')}/${gf.result.file_path}`;
      const range = req.headers.get('range');
      const up = await fetch(fileUrl, range ? { headers: { Range: range } } : {});
      const h = new Headers(cors);
      h.set('Content-Type', 'video/mp4');
      h.set('Accept-Ranges', 'bytes');
      const cl = up.headers.get('content-length'); if (cl) h.set('Content-Length', cl);
      const cr = up.headers.get('content-range'); if (cr) h.set('Content-Range', cr);
      h.set('Cache-Control', 'private, max-age=600');
      return new Response(up.body, { status: up.status, headers: h });
    } catch (e) { log(rid, 'error', 'media.failed', errInfo(e)); return new Response('err', { status: 500, headers: cors }); }
  }

  const prime = url.searchParams.get('prime');
  if (prime) {
    const hdr = { 'Access-Control-Allow-Origin': '*', 'Content-Type': 'application/json' };
    // این مسیر آپلود به تلگرام راه می‌اندازد و در چتِ مدیر پیام می‌گذارد، پس
    // نباید برای هر غریبه‌ای باز باشد. تنها صداکننده‌اش پنلِ واردشده است.
    const jwt = (req.headers.get('authorization') || '').replace(/^Bearer\s+/i, '');
    let authed = false;
    if (jwt) {
      try { const u = await supabase.auth.getUser(jwt); authed = !!(u && u.data && u.data.user); }
      catch (e) { log(rid, 'warn', 'prime.auth_failed', errInfo(e)); }
    }
    if (!authed) {
      return new Response(JSON.stringify({ ok: false, error: 'unauthorized' }), { status: 401, headers: hdr });
    }
    const out: any = { ok: true, jin: 'skip', carton: 'skip', jin_fid: null, carton_fid: null };
    try {
      const { data: p } = await supabase.from('products')
        .select('id,name,video_jin_url,video_jin_fid,video_carton_url,video_carton_fid')
        .eq('id', prime).maybeSingle();
      const { data: admins } = await supabase.from('bot_admins').select('chat_id').limit(1);
      const target = (admins && admins.length) ? Number(admins[0].chat_id) : null;
      if (p && target) {
        for (const w of ['jin', 'carton']) {
          const urlCol = w === 'jin' ? 'video_jin_url' : 'video_carton_url';
          const fidCol = w === 'jin' ? 'video_jin_fid' : 'video_carton_fid';
          if ((p as any)[fidCol]) { out[w] = 'ready'; out[w + '_fid'] = (p as any)[fidCol]; continue; }
          if (!(p as any)[urlCol]) continue;
          const r = await deliverVideo(target, p, urlCol, fidCol, '', true);
          out[w] = r.st;
          if (r.st === 'ok') {
            out[w + '_fid'] = r.fid || (p as any)[fidCol] || null;
            if (r.res && r.res.result) {
              try { await tgCall('deleteMessage', { chat_id: target, message_id: r.res.result.message_id }); } catch (_) {}
            }
          }
        }
      }
    } catch (e) { log(rid, 'error', 'prime.failed', errInfo(e)); out.ok = false; }
    return new Response(JSON.stringify(out), { headers: hdr });
  }

  if (url.searchParams.get('cron') === 'weekly') {
    const ck = await cronKey();
    if (!ck || url.searchParams.get('k') !== ck) return new Response('no', { status: 401 });
    // شکست باید دیده شود: اگر گزارش یا پشتیبان بیفتد، cron نباید «ok» بگوید،
    // وگرنه جمعه‌شبی که گزارش نیامده در سابقه‌ی زمان‌بند «موفق» ثبت می‌شود.
    const failed: string[] = [];
    try { const rep = await buildWeeklyReport(); await notifyAdmins(rep); }
    catch (e) { log(rid, 'error', 'cron.report_failed', errInfo(e)); failed.push('report'); }
    try {
      const { data: admins } = await supabase.from('bot_admins').select('chat_id').limit(1);
      if (admins && admins.length) await sendBackup(Number(admins[0].chat_id));
    } catch (e) { log(rid, 'error', 'cron.backup_failed', errInfo(e)); failed.push('backup'); }
    if (failed.length) return new Response('failed: ' + failed.join(','), { status: 500 });
    return new Response('ok');
  }
  if (url.searchParams.get('secret') !== Deno.env.get('BOT_TOKEN')) {
    return new Response('no', { status: 401 });
  }

  try {
    const update = await req.json();

    if (update.channel_post || update.edited_channel_post || update.my_chat_member) {
      return new Response('ok');
    }

    if (update.callback_query) {
      const cq = update.callback_query;
      const chatId = cq.message.chat.id;
      const data = cq.data;
      await answerCallback(cq.id);
      const s = await getSession(chatId);

      if (data === 'noop') {
        /* فقط شماره‌ی صفحه‌ست */
      } else if (data === 'ask') {
        await logEvent(chatId, 'ask');
        await setSession(chatId, { step: 'asking' });
        await send(chatId, '💬 سؤالت رو همین‌جا بنویس (یا عکس بفرست) — می‌رسه دستِ فروشگاه و همین‌جا جوابت رو می‌دیم 🌹\n(برای انصراف /start بزن)');
      } else if (data.startsWith('rp_')) {
        if (await isAdmin(chatId)) {
          const target = Number(data.slice(3));
          if (!target) { await send(chatId, 'مقصدِ جواب پیدا نشد 🙏'); }
          else {
            await setSession(chatId, { step: 'replying', reply_to: target });
            await send(chatId, '✍️ جوابت رو بنویس تا براش بفرستم:\n(برای انصراف /start بزن)');
          }
        }
      } else if (data === 'myorders') {
        await showMyOrders(chatId);
      } else if (data === 'new_order') {
        await setSession(chatId, { cart: [], customer_name: null, customer_phone: null, customer_city: null, customer_address: null, discount_pct: 0, discount_code: null, temp_order_id: null, editing_order_id: null });
        await showProducts(chatId);
      } else if (data === 'back_list' || data === 'catall' || data === 'back_cats') {
        await showCategory(chatId, -1, 0);
      } else if (data === 'catnew') {
        await showCategory(chatId, -2, 0);
      } else if (data.startsWith('pg_')) {
        const q = data.slice(3).split('_');
        await showCategory(chatId, parseInt(q[0]), parseInt(q[1]) || 0);
      } else if (data === 'repeat_last') {
        const { data: last } = await supabase.from('telegram_orders').select('*').eq('tg_user_id', chatId).order('created_at', { ascending: false }).limit(1).maybeSingle();
        if (!last) { await send(chatId, 'سفارشِ قبلی‌ای پیدا نشد.'); await showProducts(chatId); return new Response('ok'); }
        const prev = Array.isArray(last.items) ? last.items : [];
        const cart: any[] = []; const dropped: string[] = [];
        for (const it of prev) {
          const { data: pr } = await supabase.from('products').select('id,name,price').eq('id', it.product_id).maybeSingle();
          if (!pr) { dropped.push(it.name || 'یه کالا'); continue; }
          cart.push({ product_id: pr.id, name: pr.name, quantity: Number(it.quantity || 1), unit_price: Number(pr.price) });
        }
        if (!cart.length) { await send(chatId, 'متأسفانه جنسای سفارشِ قبلیت دیگه تو لیست نیست 🙏'); await showProducts(chatId); return new Response('ok'); }
        await setSession(chatId, { cart, customer_name: last.customer_name, customer_phone: last.customer_phone, customer_city: last.customer_city, customer_address: last.customer_address, discount_pct: 0, discount_code: null, step: 'confirm_repeat' });
        let sm = '🔁 <b>سفارشِ قبلیت:</b>\n'; let tot = 0;
        for (const it of cart) { tot += it.quantity * it.unit_price; sm += `• ${bidi(escH(it.name))} × ${fa(it.quantity)} = ${fa(it.quantity * it.unit_price)} ت\n`; }
        sm += `\n<b>جمع: ${fa(tot)} تومان</b>\n📍 ${escH(last.customer_address || '')}`;
        if (dropped.length) sm += `\n\n⚠️ این‌ها دیگه تو لیست نبود و حذف شد: ${dropped.map(escH).join('، ')}`;
        await send(chatId, sm, { inline_keyboard: [[{ text: '✅ ثبت با همین مشخصات', callback_data: 'repeat_go' }], [{ text: '✏️ تغییر آدرس', callback_data: 'repeat_editaddr' }], [{ text: '🛒 از اول', callback_data: 'new_order' }]] });
      } else if (data === 'repeat_go') {
        const s2 = await getSession(chatId);
        await finalizeOrder(chatId, s2, s2.customer_address || '', (cq.from && cq.from.username) || null);
      } else if (data === 'repeat_editaddr') {
        await setSession(chatId, { step: 'address' });
        await send(chatId, 'آدرسِ جدید رو بفرست:');
      } else if (data.startsWith('jin_')) {
        await logEvent(chatId, 'media', data.slice(4));
        await sendProductVideo(chatId, data.slice(4), 'jin');
      } else if (data.startsWith('crt_')) {
        await logEvent(chatId, 'media', data.slice(4));
        await sendProductVideo(chatId, data.slice(4), 'carton');
      } else if (data.startsWith('pics_')) {
        await logEvent(chatId, 'media', data.slice(5));
        await sendProductPhotos(chatId, data.slice(5));
      } else if (data.startsWith('size_')) {
        const pid = data.slice(5);
        await logEvent(chatId, 'media', pid);
        const { data: p } = await supabase.from('products').select('name,size_info').eq('id', pid).maybeSingle();
        if (p && p.size_info && String(p.size_info).trim()) {
          await send(chatId, `📏 <b>اندازه و قواره «${escH(p.name)}»:</b>\n${escH(p.size_info)}`);
        } else {
          await send(chatId, '📏 اطلاعاتِ اندازه‌ی این کالا هنوز ثبت نشده 🙏');
        }
      } else if (data.startsWith('paynow_')) {
        await logEvent(chatId, 'pay_click');
        const oid = data.slice(7);
        const { data: ord } = await supabase.from('telegram_orders').select('id,total,cards,card_file_id,paid_confirmed_at,customer_name,customer_phone').eq('id', oid).maybeSingle();
        const talkKb = ord ? { inline_keyboard: [[{ text: '💬 دربارهٔ واریز حرف بزنم', callback_data: `paytalk_${ord.id}` }]] } : undefined;
        if (!ord) {
          await send(chatId, 'این سفارش پیدا نشد 🙏');
        } else if (ord.paid_confirmed_at) {
          await send(chatId, '✅ پرداختِ این سفارش قبلاً تأیید شده 🌹');
        } else if (cardsOf(ord).length) {
          await resendCards(chatId, ord);
          const rem = remainOf(ord);
          let t2 = `🧾 جمعِ سفارشت: <b>${fa(ord.total)} تومان</b>\n`;
          // سه حالتِ جدا. «مونده صفر است» و «مونده را نتوانستم بخوانم» نباید یک
          // شکل داشته باشند — دومی یعنی عدد نداریم، نه اینکه چیزی نمانده.
          if (rem === null) t2 += '⚠️ مبلغِ کارت‌ها خونده نشد — لطفاً همین‌جا بهمون بگو.';
          else if (rem > 0) t2 += `⏳ <b>${fa(rem)} تومان</b> از مبلغ هنوز کارتش برات نرفته — همین‌جا برات می‌فرستیم.`;
          else t2 += '✅ کارتِ همه‌ی مبلغ برات رفته.';
          t2 += '\n\nبعدِ هر واریز، <b>عکسِ فیش</b> رو همین‌جا بفرست 🙏';
          await send(chatId, t2, talkKb);
          await setSession(chatId, { step: 'awaiting_receipt', temp_order_id: ord.id });
        } else {
          await send(chatId, '💳 چند لحظه صبر کن — الان شماره‌کارت رو برات می‌فرستیم 🌹', talkKb);
          const { data: admins } = await supabase.from('bot_admins').select('chat_id');
          const req2 = `🔔 <b>مشتری می‌خواد پرداخت کنه</b>\n👤 ${escH(ord.customer_name || '')}\n📞 ${escH(ord.customer_phone || '')}\n\n` + cardPrompt(ord, Math.round(Number(ord.total) || 0));
          for (const a of (admins || [])) {
            try {
              await getSession(Number(a.chat_id));
              await setSession(Number(a.chat_id), { step: 'awaiting_card', temp_order_id: ord.id });
              await send(Number(a.chat_id), req2);
            } catch (_) {}
          }
        }
      } else if (data.startsWith('paytalk_')) {
        const oid = data.slice(8);
        const { data: ord } = await supabase.from('telegram_orders').select('id,tg_user_id,total,cards,paid_confirmed_at').eq('id', oid).maybeSingle();
        if (!ord || Number(ord.tg_user_id) !== Number(chatId)) {
          await send(chatId, 'این سفارش پیدا نشد 🙏');
        } else if (ord.paid_confirmed_at) {
          await send(chatId, '✅ پرداختِ این سفارش تأیید شده — اگه بازم سؤالی داری /سوال رو بزن 🌹');
        } else {
          await logEvent(chatId, 'ask');
          await setSession(chatId, { step: 'pay_ask', temp_order_id: ord.id });
          const rem = remainOf(ord);
          let t2 = '💬 بنویس چطور می‌خوای واریز کنی — مثلاً «الان نصفش رو می‌زنم، بقیه رو فردا» یا «کارتِ دوم بفرست».\n\n';
          t2 += `🧾 جمعِ سفارشت: <b>${fa(ord.total)} تومان</b>`;
          if (rem !== null && rem > 0 && rem !== Math.round(Number(ord.total) || 0)) t2 += `\n⏳ مونده: <b>${fa(rem)} تومان</b>`;
          t2 += '\n\n(می‌تونی عکس هم بفرستی.)';
          await send(chatId, t2);
        }
      } else if (data.startsWith('sendcard_')) {
        if (await isAdmin(chatId)) {
          const oid = data.slice(9);
          const { data: ord } = await supabase.from('telegram_orders').select('id,total,cards').eq('id', oid).maybeSingle();
          if (!ord) {
            await send(chatId, 'این سفارش پیدا نشد 🙏');
          } else {
            const rem = remainOf(ord);
            if (rem === null) {
              await send(chatId, '⚠️ مبلغِ کارت‌های قبلیِ این سفارش خونده نشد — تا درست نشده کارتِ تازه نفرست، وگرنه ممکنه از مشتری بیشتر از بدهیش پول بخوای.');
            } else if (rem <= 0) {
              await send(chatId, `✅ کلِ <b>${fa(ord.total)} تومان</b> این سفارش قبلاً روی کارت‌ها تقسیم شده — چیزی نمونده.`,
                { inline_keyboard: [[{ text: '✅ پرداخت شد (تأیید به مشتری)', callback_data: `paid_${ord.id}` }]] });
            } else {
              await setSession(chatId, { step: 'awaiting_card', temp_order_id: ord.id });
              await send(chatId, cardPrompt(ord, rem));
            }
          }
        }
      } else if (data.startsWith('paid_')) {
        if (await isAdmin(chatId)) {
          const oid = data.slice(5);
          const { data: ord } = await supabase.from('telegram_orders').select('id,tg_user_id,total').eq('id', oid).maybeSingle();
          if (ord) {
            await supabase.from('telegram_orders').update({ paid_confirmed_at: new Date().toISOString() }).eq('id', ord.id);
            if (ord.tg_user_id) await logEvent(Number(ord.tg_user_id), 'paid', null, { total: Number(ord.total || 0) });
            if (ord.tg_user_id) {
              try { await setSession(Number(ord.tg_user_id), { step: 'idle', temp_order_id: null }); } catch (_) {}
              await send(Number(ord.tg_user_id), `✅ پرداختِ <b>${fa(ord.total)} تومان</b> رسید و تأیید شد. سفارشت در حالِ آماده‌سازیه 🌹`);
            }
            await send(chatId, '✅ تأیید شد و به مشتری هم خبر دادیم.');
          } else {
            await send(chatId, 'این سفارش پیدا نشد 🙏');
          }
        }
      } else if (data.startsWith('edit_')) {
        const oid = data.slice(5);
        const { data: ord } = await supabase.from('telegram_orders').select('*').eq('id', oid).maybeSingle();
        if (!ord || Number(ord.tg_user_id) !== Number(chatId)) {
          await send(chatId, 'این سفارش پیدا نشد 🙏');
        } else if (ord.status !== 'new' || ord.invoice_id || ord.paid_confirmed_at || ord.card_sent_at) {
          await send(chatId, 'این سفارش رفته تو مرحله‌ی پردازش و دیگه قابلِ ویرایش نیست 🙏');
        } else {
          const prev = Array.isArray(ord.items) ? ord.items : [];
          const cart: any[] = []; const dropped: string[] = [];
          for (const it of prev) {
            const { data: pr } = await supabase.from('products').select('id,name,price').eq('id', it.product_id).maybeSingle();
            if (!pr) { dropped.push(it.name || 'یه کالا'); continue; }
            cart.push({ product_id: pr.id, name: pr.name, quantity: Number(it.quantity || 1), unit_price: Number(pr.price) });
          }
          await setSession(chatId, { cart, step: 'edit_cart', editing_order_id: ord.id, temp_product_id: null, customer_name: ord.customer_name, customer_phone: ord.customer_phone, customer_city: ord.customer_city, customer_address: ord.customer_address, discount_pct: 0, discount_code: null });
          await showEditCart(chatId, dropped.length ? ('\n⚠️ این‌ها دیگه تو لیست نبود و حذف شد: ' + dropped.map(escH).join('، ')) : '');
        }
      } else if (data.startsWith('edel_')) {
        if (s.step === 'edit_cart' && s.editing_order_id) {
          const idx = parseInt(data.slice(5));
          const cart = s.cart || [];
          if (idx >= 0 && idx < cart.length) cart.splice(idx, 1);
          await setSession(chatId, { cart });
          await showEditCart(chatId);
        }
      } else if (data === 'edadd') {
        if (s.editing_order_id) { await showProducts(chatId); }
      } else if (data === 'edok') {
        if (s.step === 'edit_cart' && s.editing_order_id) {
          const cart = s.cart || [];
          if (!cart.length) { await send(chatId, 'سبد خالیه 🙏'); await showEditCart(chatId); }
          else {
            const { data: ord } = await supabase.from('telegram_orders').select('id,status,invoice_id,paid_confirmed_at,card_sent_at,note').eq('id', s.editing_order_id).maybeSingle();
            if (!ord || ord.status !== 'new' || ord.invoice_id || ord.paid_confirmed_at || ord.card_sent_at) {
              await setSession(chatId, { step: 'idle', editing_order_id: null });
              await send(chatId, 'این سفارش همین الان رفت تو پردازش و تغییرت ثبت نشد 🙏');
            } else {
              const total = cart.reduce((sum: number, it: any) => sum + it.quantity * it.unit_price, 0);
              await supabase.from('telegram_orders').update({ items: cart, total, note: null }).eq('id', ord.id);
              await setSession(chatId, { step: 'idle', editing_order_id: null, cart: [] });
              let sm = '✅ سفارشت ویرایش شد!\n\n<b>سفارشِ جدید:</b>\n';
              for (const it of cart) sm += `• ${bidi(escH(it.name))} × ${fa(it.quantity)} = ${fa(it.quantity * it.unit_price)} ت\n`;
              sm += `<b>جمعِ کل: ${fa(total)} تومان</b>`;
              if (ord.note) sm += '\n\n(کدِ تخفیفِ قبلی برداشته شد)';
              await send(chatId, sm, { inline_keyboard: [[{ text: '💳 می‌خوام پرداخت کنم', callback_data: `paynow_${ord.id}` }], [{ text: '✏️ ویرایشِ دوباره', callback_data: `edit_${ord.id}` }]] });
              try {
                const { data: admins } = await supabase.from('bot_admins').select('chat_id');
                let am = `🔄 <b>مشتری سفارشش رو ویرایش کرد</b>\n👤 ${escH(s.customer_name || '')}\n📞 ${escH(s.customer_phone || '')}\n\n`;
                for (const it of cart) am += `• ${bidi(escH(it.name))} × ${fa(it.quantity)} = ${fa(it.quantity * it.unit_price)} ت\n`;
                am += `<b>جمعِ جدید: ${fa(total)} تومان</b>`;
                for (const a of (admins || [])) { try { await send(Number(a.chat_id), am, { inline_keyboard: [[{ text: '💳 فرستادنِ کارت به مشتری', callback_data: `sendcard_${ord.id}` }]] }); } catch (_) {} }
              } catch (_) {}
            }
          }
        }
      } else if (data === 'edcancel') {
        const oid = s.editing_order_id;
        await setSession(chatId, { step: 'idle', editing_order_id: null, cart: [] });
        if (oid) await send(chatId, 'باشه، سفارش همون قبلی موند ✅', { inline_keyboard: [[{ text: '💳 می‌خوام پرداخت کنم', callback_data: `paynow_${oid}` }]] });
        else await send(chatId, 'باشه ✅');
      } else if (data.startsWith('buy_')) {
        const pid = data.slice(4);
        await setSession(chatId, { temp_product_id: pid, step: 'qty' });
        await send(chatId, 'چند عدد می‌خوای؟\n\n' + PACK_HINT);
      } else if (data.startsWith('p_')) {
        await showProductDetail(chatId, data.slice(2));
      } else if (data === 'done_items') {
        if (s.editing_order_id) { await setSession(chatId, { step: 'edit_cart' }); await showEditCart(chatId); return new Response('ok'); }
        const cart = s.cart || [];
        if (cart.length === 0) {
          await send(chatId, 'هنوز چیزی انتخاب نکردی 🙂');
          await showProducts(chatId);
        } else {
          await logEvent(chatId, 'checkout', null, { items: cart.length });
          const { data: anyCode } = await supabase.from('discount_codes').select('id').eq('active', true).limit(1);
          if (anyCode && anyCode.length) {
            await setSession(chatId, { step: 'discount' });
            await send(chatId, '🎟 کدِ تخفیف داری؟ اگه داری بفرست، وگرنه بنویس «نه».');
          } else {
            await setSession(chatId, { step: 'name' });
            await send(chatId, 'اسمت یا اسمِ فروشگاهت رو بنویس:');
          }
        }
      }
      return new Response('ok');
    }

    if (update.message) {
      const msg = update.message;
      const chatId = msg.chat.id;
      const tgUser = msg.from?.username || null;

      const pic = (msg.photo && msg.photo.length) ? msg.photo[msg.photo.length - 1] : null;
      if (pic) {
        const ps = await getSession(chatId);
        if (ps.step === 'awaiting_card' && ps.temp_order_id && (await isAdmin(chatId))) {
          const { data: ord } = await supabase.from('telegram_orders').select('id,tg_user_id,total,cards,card_sent_at').eq('id', ps.temp_order_id).maybeSingle();
          if (!ord) { await setSession(chatId, { step: 'idle', temp_order_id: null }); await send(chatId, 'سفارش پیدا نشد 🙏'); return new Response('ok'); }
          if (!ord.tg_user_id) { await setSession(chatId, { step: 'idle', temp_order_id: null }); await send(chatId, 'چتِ مشتریِ این سفارش ثبت نشده 🙏'); return new Response('ok'); }
          const rem0 = remainOf(ord);
          if (rem0 === null) {
            await setSession(chatId, { step: 'idle', temp_order_id: null });
            await send(chatId, '⚠️ مبلغِ کارت‌های قبلیِ این سفارش خونده نشد — کارت فرستاده نشد.');
            return new Response('ok');
          }
          if (rem0 <= 0) {
            await setSession(chatId, { step: 'idle', temp_order_id: null });
            await send(chatId, `✅ کلِ <b>${fa(ord.total)} تومان</b> قبلاً روی کارت‌ها تقسیم شده — این کارت فرستاده نشد.`);
            return new Response('ok');
          }
          /* مبلغ از کپشنِ همان عکس خوانده می‌شود؛ نبودنِ کپشن یعنی «همه‌ی مانده».
             ⚠️ روی ورودیِ نامعتبر **نشست بسته نمی‌شود** — مدیر باید بتواند همان
             عکس را با کپشنِ درست دوباره بفرستد، نه اینکه از اولِ مسیر شروع کند.
             و مبلغ حدس زده نمی‌شود (API-07): «۵ میلیون» به ۵ تومان تبدیل نمی‌شود. */
          let amount = rem0;
          const capIn = String(msg.caption || '').trim();
          if (capIn) {
            const want = parseToman(capIn);
            if (want === null) {
              await send(chatId, `مبلغِ کپشن رو نفهمیدم 🙏 ${AMOUNT_HINT}\n\n⏳ مونده: <b>${fa(rem0)} تومان</b>\nعکس رو با کپشنِ درست دوباره بفرست، یا بدونِ کپشن بفرست تا همه‌ی مونده روش بره.`);
              return new Response('ok');
            }
            if (want > rem0) {
              await send(chatId, `این مبلغ از مونده بیشتره 🙏\n⏳ مونده: <b>${fa(rem0)} تومان</b>\nعکس رو با مبلغِ درست دوباره بفرست.`);
              return new Response('ok');
            }
            amount = want;
          }
          const at = new Date().toISOString();
          const list = cardsOf(ord).concat([{ fid: pic.file_id, amount, at }]);
          const upd: any = { cards: list };
          if (!ord.card_sent_at) { upd.card_file_id = pic.file_id; upd.card_sent_at = at; }
          /* **اول ثبت، بعد پیام به مشتری.** اگر نوشتن نشود و ما مبلغ را گفته
             باشیم، دفعه‌ی بعد مانده همان مبلغ را دوباره می‌خواهد — یعنی از مشتری
             دوبار پول خواسته‌ایم و هیچ خطایی هم دیده نمی‌شود. */
          const { error: cardErr } = await supabase.from('telegram_orders').update(upd).eq('id', ord.id);
          if (cardErr) {
            await send(chatId, '⚠️ کارت ثبت نشد و برای مشتری هم نرفت — یه بارِ دیگه بفرستش 🙏');
            return new Response('ok');
          }
          await setSession(chatId, { step: 'idle', temp_order_id: null });
          const after = Math.max(0, rem0 - amount);
          const custCap = (list.length === 1 && after === 0)
            ? `💳 مبلغِ <b>${fa(amount)} تومان</b> رو به این کارت واریز کن.\n\nبعدِ واریز، <b>عکسِ فیش</b> رو همین‌جا بفرست 🙏`
            : `💳 <b>کارتِ ${fa(list.length)}</b> — مبلغِ <b>${fa(amount)} تومان</b> رو به این کارت واریز کن.\n\n`
              + `🧾 جمعِ سفارش: ${fa(ord.total)} تومان\n`
              + (after > 0
                  ? `⏳ بعدش <b>${fa(after)} تومان</b> می‌مونه که کارتش رو جدا برات می‌فرستیم.`
                  : `✅ با این کارت، کلِ مبلغِ سفارشت کامل می‌شه.`)
              + `\n\nبعدِ هر واریز، <b>عکسِ فیش</b> رو همین‌جا بفرست 🙏`;
          await sendPhoto(Number(ord.tg_user_id), pic.file_id, custCap,
            { inline_keyboard: [[{ text: '💬 دربارهٔ واریز حرف بزنم', callback_data: `paytalk_${ord.id}` }]] });
          try { await getSession(Number(ord.tg_user_id)); await setSession(Number(ord.tg_user_id), { step: 'awaiting_receipt', temp_order_id: ord.id }); } catch (_) {}
          try {
            const { data: admins } = await supabase.from('bot_admins').select('chat_id');
            for (const a of (admins || [])) {
              if (Number(a.chat_id) === Number(chatId)) continue;
              const os = await getSession(Number(a.chat_id));
              if (os && os.step === 'awaiting_card' && os.temp_order_id === ord.id) {
                await setSession(Number(a.chat_id), { step: 'idle', temp_order_id: null });
                await send(Number(a.chat_id), 'ℹ️ کارتِ این سفارش رو مدیرِ دیگه‌ای فرستاد.');
              }
            }
          } catch (_) {}
          const admRows: any[] = [];
          if (after > 0) admRows.push([{ text: `💳 فرستادنِ کارتِ بعدی (${fa(after)} ت)`, callback_data: `sendcard_${ord.id}` }]);
          admRows.push([{ text: '✅ پرداخت شد (تأیید به مشتری)', callback_data: `paid_${ord.id}` }]);
          await send(chatId, `✅ کارت برای مشتری رفت — <b>${fa(amount)} تومان</b> روش نوشته شد.\n`
            + (after > 0
                ? `⏳ مونده: <b>${fa(after)} تومان</b> از ${fa(ord.total)} تومان.`
                : `✅ کلِ ${fa(ord.total)} تومان تقسیم شد.`), { inline_keyboard: admRows });
          return new Response('ok');
        }
        if (ps.step === 'awaiting_receipt' && ps.temp_order_id) {
          const { data: ord } = await supabase.from('telegram_orders').select('id,total,cards,customer_name,customer_phone,customer_city').eq('id', ps.temp_order_id).maybeSingle();
          await setSession(chatId, { step: 'idle', temp_order_id: null });
          if (!ord) { await send(chatId, 'سفارشت پیدا نشد 🙏'); return new Response('ok'); }
          await supabase.from('telegram_orders').update({ receipt_file_id: pic.file_id, receipt_sent_at: new Date().toISOString() }).eq('id', ord.id);
          await logEvent(chatId, 'receipt', null, { total: Number(ord.total || 0) });
          await send(chatId, '🧾 فیشت رسید، ممنون! بررسیش می‌کنیم 🌹');
          try {
            const { data: admins } = await supabase.from('bot_admins').select('chat_id');
            /* با پرداختِ تکه‌تکه، «فیش رسید» به‌تنهایی کافی نیست: مدیر باید بداند
               این فیش مالِ کدام تکه است و چقدر مانده. بدونِ این، فیشِ نصفه شبیهِ
               فیشِ کامل است و «پرداخت شد» زودتر از موقع زده می‌شود. */
            const rcCards = cardsOf(ord);
            const rcRem = remainOf(ord);
            let split = '';
            if (rcCards.length > 1) {
              /* ⚠️ دنباله‌ی «A + B» بدونِ ایزوله در بندِ راست‌به‌چپ **وارونه** دیده
                 می‌شود — هر عدد یک اجرای جدا می‌شود و ترتیبِ دیداری‌شان برعکس. با
                 همان عکسِ بازرس در پنل پیدا شد و اینجا هم صادق است. ترتیب معنی
                 دارد: کارتِ اول، کارتِ دوم. */
              split = `\n💳 کارت‌ها: ${bidi(rcCards.map((c: any) => fa(Number(c && c.amount))).join(' + '))}`;
            }
            if (rcRem === null) split += '\n⚠️ مانده خونده نشد';
            else if (rcRem > 0) split += `\n⏳ هنوز <b>${fa(rcRem)} تومان</b> کارتش نرفته`;
            const cap = `🧾 <b>فیشِ واریزی رسید</b>\n👤 ${escH(ord.customer_name || '')}\n📞 ${escH(ord.customer_phone || '')}\n🏙 ${escH(ord.customer_city || '')}\n💰 مبلغِ سفارش: <b>${fa(ord.total)} تومان</b>${split}`;
            for (const a of (admins || [])) {
              try { await sendPhoto(Number(a.chat_id), pic.file_id, cap, { inline_keyboard: [[{ text: '✅ پرداخت شد (تأیید به مشتری)', callback_data: `paid_${ord.id}` }]] }); } catch (_) {}
            }
          } catch (_) {}
          return new Response('ok');
        }
        if (ps.step === 'pay_ask') { await forwardQuestion(chatId, msg, msg.caption || '', pic.file_id, ps.temp_order_id); return new Response('ok'); }
        if (ps.step === 'asking') { await forwardQuestion(chatId, msg, msg.caption || '', pic.file_id); return new Response('ok'); }
        if (await isAdmin(chatId)) {
          await send(chatId, 'عکسِ کالاها رو از خودِ پنل اضافه کن 🙏');
        }
        return new Response('ok');
      }

      const vid = msg.video || (msg.document && /video/.test(msg.document.mime_type || '') ? msg.document : null);
      if (vid) {
        const vs = await getSession(chatId);
        if (vs.step === 'pay_ask') { await forwardQuestion(chatId, msg, msg.caption || '(ویدیو فرستاد)', null, vs.temp_order_id); return new Response('ok'); }
        if (vs.step === 'asking') { await forwardQuestion(chatId, msg, msg.caption || '(ویدیو فرستاد)', null); return new Response('ok'); }
        if (await isAdmin(chatId)) {
          await send(chatId, 'فیلمِ جین و کارتن رو از خودِ پنل بذار 🙏');
        }
        return new Response('ok');
      }

      if (msg.text) {
        const text = msg.text.trim();
        const cmdA = text.normalize('NFKC').replace(/[^\x21-\x7E]/g, '').replace(/@[A-Za-z0-9_]+$/i, '');
        const cmdF = text.replace(/[\p{Cf}\s]/gu, '').replace(/@[A-Za-z0-9_]+$/i, '');
        const s = await getSession(chatId);

        if (cmdA === '/start') { await logEvent(chatId, 'start'); await showMain(chatId); return new Response('ok'); }
        if (cmdF === '/سوال' || cmdF === '/سؤال' || cmdA === '/ask') {
          await setSession(chatId, { step: 'asking' });
          await send(chatId, '💬 سؤالت رو بنویس (یا عکس بفرست) — می‌رسه دستِ فروشگاه 🌹');
          return new Response('ok');
        }
        if (cmdF === '/سفارشات' || cmdA === '/myorders') { await showMyOrders(chatId); return new Response('ok'); }
        if (['/id','/id/','id/'].includes(cmdA.toLowerCase())) { await send(chatId, `آیدیِ عددیِ این چت:\n<code>${chatId}</code>`); return new Response('ok'); }

        if (cmdF === '/گزارش' || cmdA === '/report') { if (await isAdmin(chatId)) { await send(chatId, await buildWeeklyReport()); } return new Response('ok'); }
        if (cmdF === '/پشتیبان' || cmdA === '/backup') {
          if (await isAdmin(chatId)) {
            await send(chatId, '💾 دارم پشتیبان می‌گیرم، چند لحظه…');
            const r = await sendBackup(chatId);
            if (!r || !r.ok) await send(chatId, 'پشتیبان‌گیری خطا خورد 🙏');
          }
          return new Response('ok');
        }
        if (cmdF === '/پخش' || cmdA === '/broadcast') { if (await isAdmin(chatId)) { await setSession(chatId, { step: 'broadcasting' }); await send(chatId, '📢 متنِ پیام رو بفرست.'); } return new Response('ok'); }

        if (s.step === 'pay_ask') { await forwardQuestion(chatId, msg, text, null, s.temp_order_id); return new Response('ok'); }
        if (s.step === 'asking') { await forwardQuestion(chatId, msg, text, null); return new Response('ok'); }
        if (s.step === 'replying') {
          if (!(await isAdmin(chatId))) { await setSession(chatId, { step: 'idle', reply_to: null }); }
          else {
            const target = Number(s.reply_to || 0);
            await setSession(chatId, { step: 'idle', reply_to: null });
            if (!target) { await send(chatId, 'مقصدِ جواب پیدا نشد 🙏'); return new Response('ok'); }
            const r = await send(target, `📩 <b>پاسخ از مدلند قشم</b>\n\n${escH(text)}`, { inline_keyboard: [[{ text: '💬 بازم سؤال دارم', callback_data: 'ask' }], [{ text: '🛒 ثبتِ سفارش', callback_data: 'new_order' }]] });
            await send(chatId, (r && r.ok) ? '✅ جوابت براش رفت.' : 'نتونستم برسونم 🙏');
            return new Response('ok');
          }
        }
        if (s.step === 'broadcasting') {
          if (!(await isAdmin(chatId))) { await setSession(chatId, { step: 'idle' }); }
          else {
            const { data: rows } = await supabase.from('telegram_orders').select('tg_user_id').not('tg_user_id', 'is', null);
            const ids = [...new Set((rows || []).map((r: any) => Number(r.tg_user_id)).filter(Boolean))];
            let sent = 0; for (const uid of ids) { try { await send(uid, text); sent++; } catch (_) {} }
            await setSession(chatId, { step: 'idle' });
            await send(chatId, `✅ پیام به ${fa(sent)} نفر فرستاده شد.`);
            return new Response('ok');
          }
        }
        if (s.step === 'awaiting_card') { await send(chatId, '📸 اینجا باید <b>عکسِ کارت</b> رو بفرستی.'); return new Response('ok'); }
        if (s.step === 'awaiting_receipt') { await send(chatId, '🧾 اینجا باید <b>عکسِ فیش</b> رو بفرستی.'); return new Response('ok'); }

        if (s.step === 'qty') {
          const qty = parseInt(text.replace(/[۰-۹]/g, (d: string) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d).toString()));
          if (!qty || qty <= 0) { await send(chatId, 'یه عددِ درست بفرست 🙏\n\n' + PACK_HINT); return new Response('ok'); }
          if (!packOk(qty)) {
            // نزدیک‌ترین تعدادهای درست را پیشنهاد بده — «مضربِ ۶ بفرست» به‌تنهایی
            // یعنی مشتری باید خودش حساب کند، و همان‌جا رها می‌کند.
            const lo = Math.floor(qty / PACK_STEP) * PACK_STEP;
            let m = '❌ تعداد باید مضربی از ۶ باشه، چون کمترین بسته‌مون نیم‌جین (۶ عدد) است.';
            m += (lo >= PACK_STEP)
              ? `\n\nمنظورت <b>${fa(lo)}</b> بود یا <b>${fa(lo + PACK_STEP)}</b>؟`
              : `\n\nکمترین تعداد <b>۶</b> عدده.`;
            await send(chatId, m + '\n\n' + PACK_HINT);
            return new Response('ok');
          }
          const { data: prod } = await supabase.from('products').select('id,name,price').eq('id', s.temp_product_id).maybeSingle();
          if (!prod) { await setSession(chatId, { temp_product_id: null, step: 'choosing' }); await send(chatId, 'این کالا دیگه تو لیست نیست 🙏'); await showProducts(chatId); return new Response('ok'); }
          const cart = s.cart || [];
          cart.push({ product_id: prod.id, name: prod.name, quantity: qty, unit_price: Number(prod.price) });
          await logEvent(chatId, 'cart_add', prod.id, { qty, unit_price: Number(prod.price) });
          if (s.editing_order_id) {
            await setSession(chatId, { cart, temp_product_id: null, step: 'edit_cart' });
            await send(chatId, `«${bidi(escH(prod.name))}» × ${fa(qty)} اضافه شد ✅`);
            await showEditCart(chatId);
          } else {
            await setSession(chatId, { cart, temp_product_id: null });
            await send(chatId, `«${bidi(escH(prod.name))}» × ${fa(qty)} اضافه شد ✅`);
            await showProducts(chatId);
          }
        } else if (s.step === 'name') {
          await setSession(chatId, { customer_name: text, step: 'phone' });
          await send(chatId, 'شماره تماست رو بفرست:');
        } else if (s.step === 'phone') {
          await setSession(chatId, { customer_phone: text, step: 'city' });
          await send(chatId, 'شهرت رو بنویس:');
        } else if (s.step === 'city') {
          await setSession(chatId, { customer_city: text, step: 'address' });
          await send(chatId, 'آدرسِ کاملت رو بنویس:');
        } else if (s.step === 'address') {
          await finalizeOrder(chatId, s, text, tgUser);
        } else if (s.step === 'discount') {
          const t = text.trim();
          if (/^(نه|ندارم|خیر|خير|رد|no|skip|-)$/i.test(t)) {
            await setSession(chatId, { step: 'name' });
            await send(chatId, 'باشه! اسمت یا اسمِ فروشگاهت رو بنویس:');
          } else {
            const term = t.replace(/[%_,().]/g, '');
            const { data: codes } = await supabase.from('discount_codes').select('code,percent').eq('active', true).ilike('code', term).limit(1);
            if (codes && codes.length) {
              await setSession(chatId, { discount_pct: Number(codes[0].percent || 0), discount_code: codes[0].code, step: 'name' });
              await send(chatId, `✅ کدِ «${escH(codes[0].code)}» اعمال شد: ${fa(codes[0].percent)}٪ تخفیف.\nحالا اسمت رو بنویس:`);
            } else {
              await send(chatId, 'این کد معتبر نیست 🙏 دوباره بفرست، یا بنویس «نه».');
            }
          }
        } else if (s.step === 'choosing') {
          const term = text.trim().replace(/[%_,().]/g, '');
          if (term.length < 2) { await send(chatId, 'یه اسمِ کامل‌تر بزن 🙂'); return new Response('ok'); }
          const { data: found } = await supabase.from('products').select('id,name,price').ilike('name', `%${term}%`).limit(15);
          if (!found || !found.length) { await send(chatId, `چیزی با «${escH(text.trim())}» پیدا نشد.`, { inline_keyboard: [[{ text: '💬 از فروشگاه بپرس', callback_data: 'ask' }], [{ text: '📋 همه‌ی کالاها', callback_data: 'catall' }]] }); return new Response('ok'); }
          const fb: any = found.map((p: any) => [{ text: `${bidi(p.name)} — ${fa(p.price)} ت`, callback_data: `p_${p.id}` }]);
          fb.push([{ text: '✅ تمومِ خرید و ادامه', callback_data: 'done_items' }]);
          await send(chatId, `نتایجِ «${escH(text.trim())}»:`, { inline_keyboard: fb });
        } else {
          await showMain(chatId);
        }
        return new Response('ok');
      }

      return new Response('ok');
    }

    return new Response('ok');
  } catch (e) {
    log(rid, 'error', 'webhook.failed', errInfo(e));
    return new Response('ok');
  }
});
