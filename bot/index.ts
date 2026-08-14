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
      // @ts-ignore
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

function fa(n: number) {
  return Math.round(n || 0).toLocaleString('en-US')
    .replace(/[0-9]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[+d]);
}

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

function orderStatusFa(o: any) {
  if (o.status === 'cancelled') return '❌ لغو شده';
  if (o.invoice_id) return '📦 فاکتورش صادر شد';
  if (o.paid_confirmed_at) return '✅ پرداخت تأیید شد';
  if (o.receipt_sent_at) return '🧾 فیشت رسید — در حالِ بررسی';
  if (o.card_sent_at) return '💳 کارت فرستاده شد — منتظرِ فیش';
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

async function forwardQuestion(chatId: number, msg: any, text: string, photoId: string | null) {
  const s = await getSession(chatId);
  const from = msg && msg.from ? msg.from : {};
  const who = (s && s.customer_name) || from.first_name || from.username || 'مشتری';
  const uname = from.username ? ' (@' + from.username + ')' : '';
  const phone = (s && s.customer_phone) ? '\n📞 ' + escH(s.customer_phone) : '';
  const body = String(text || '').trim();
  const cap = `💬 <b>سؤال از مشتری</b>\n👤 ${escH(who)}${escH(uname)}${phone}\n\n${escH(body || '(بدونِ متن)')}`;
  const kb = { inline_keyboard: [[{ text: '✍️ جواب بده', callback_data: 'rp_' + chatId }]] };
  const { data: admins } = await supabase.from('bot_admins').select('chat_id');
  let sent = 0;
  for (const a of (admins || [])) {
    try {
      const r = photoId ? await sendPhoto(Number(a.chat_id), photoId, cap, kb) : await send(Number(a.chat_id), cap, kb);
      if (r && r.ok) sent++;
    } catch (_) {}
  }
  await setSession(chatId, { step: 'idle' });
  if (sent) await send(chatId, '✅ سؤالت رسید دستِ فروشگاه — به‌زودی همین‌جا جوابت رو می‌دیم 🌹');
  else await send(chatId, 'الان نتونستم پیامت رو برسونم 🙏 یه‌بارِ دیگه امتحان کن.');
}

const BACKUP_TABLES = ['settings','products','customers','invoices','invoice_items','payments','returns','expenses','salaries','employees','shipments','quotes','discount_codes','telegram_orders'];
const BACKUP_FA: Record<string,string> = { products:'کالا', customers:'مشتری', invoices:'فاکتور', invoice_items:'قلمِ فاکتور', payments:'پرداخت', returns:'مرجوعی', expenses:'خرج', salaries:'حقوق', employees:'کارمند', shipments:'بار', quotes:'پیش‌فاکتور', discount_codes:'کدِ تخفیف', telegram_orders:'سفارشِ ربات' };

async function buildBackup() {
  const out: any = { _saved_at: new Date().toISOString(), _shop: 'مدلند قشم' };
  for (const t of BACKUP_TABLES) {
    const rows: any[] = [];
    try {
      let from = 0;
      while (true) {
        const { data, error } = await supabase.from(t).select('*').range(from, from + 999);
        if (error || !data) break;
        rows.push(...data);
        if (data.length < 1000) break;
        from += 1000;
      }
    } catch (_) {}
    out[t] = rows;
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
  const cap = `💾 <b>پشتیبانِ کاملِ مدلند قشم</b>\n${parts.length ? parts.join(' · ') : 'فعلاً داده‌ای ثبت نشده'}\n\nاین فایل همه‌چیزه: کالاها، مشتریا، فاکتورا، پرداختا و تنظیمات (${fa(kb)} کیلوبایت).\n📌 یه جای امن نگهش دار.`;
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
    .select('id,total,items,created_at,status,invoice_id,paid_confirmed_at,receipt_sent_at,card_sent_at')
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
  for (const p of slice) btns.push([{ text: `${isNew ? '🆕 ' : ''}${p.name} — ${fa(p.price)} ت`, callback_data: `p_${p.id}` }]);
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
  cart.forEach((it: any, i: number) => kb.push([{ text: `❌ ${it.name} × ${fa(it.quantity)} — ${fa(it.quantity * it.unit_price)} ت`, callback_data: `edel_${i}` }]));
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
  let summary = '✅ سفارشت ثبت شد! ممنون 🌹\n\n<b>خلاصه‌ی سفارش:</b>\n';
  for (const it of cart) summary += `• ${escH(it.name)} × ${fa(it.quantity)} = ${fa(it.quantity * it.unit_price)} ت\n`;
  if (dpct > 0) summary += `\nتخفیف با کدِ ${escH(s.discount_code)}: ${fa(dpct)}٪ (از ${fa(raw)})`;
  summary += `\n<b>جمعِ کل: ${fa(total)} تومان</b>\n\nهر وقت خواستی پرداخت کنی دکمه‌ی زیر رو بزن 👇`;
  await setSession(chatId, { step: 'idle', cart: [] });
  await send(chatId, summary, { inline_keyboard: [[{ text: '💳 می‌خوام پرداخت کنم', callback_data: `paynow_${newOrder.id}` }], [{ text: '✏️ ویرایشِ سفارش', callback_data: `edit_${newOrder.id}` }]] });
  try {
    const { data: admins } = await supabase.from('bot_admins').select('chat_id');
    if (admins && admins.length) {
      let am = `🔔 <b>سفارشِ جدید از ربات</b>\n👤 ${escH(s.customer_name)}\n📞 ${escH(s.customer_phone)}\n🏙 ${escH(s.customer_city)}\n📍 ${escH(addressText)}\n\n`;
      for (const it of cart) am += `• ${escH(it.name)} × ${fa(it.quantity)} = ${fa(it.quantity * it.unit_price)} ت\n`;
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

Deno.serve(async (req) => {
  const url = new URL(req.url);

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
      catch (e) { console.error('mediatoken auth failed', e); }
    }
    if (!authed) {
      return new Response(JSON.stringify({ ok: false, error: 'unauthorized' }), { status: 401, headers: hdr });
    }
    const w = url.searchParams.get('which') === 'carton' ? 'carton' : 'jin';
    const exp = Math.floor(Date.now() / 1000) + MED_TTL;
    return new Response(JSON.stringify({ ok: true, tok: await medSign(mtok, w, exp) }), { headers: hdr });
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
    } catch (e) { console.error(e); return new Response('err', { status: 500, headers: cors }); }
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
      catch (e) { console.error('prime auth failed', e); }
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
    } catch (e) { console.error(e); out.ok = false; }
    return new Response(JSON.stringify(out), { headers: hdr });
  }

  if (url.searchParams.get('cron') === 'weekly') {
    const ck = await cronKey();
    if (!ck || url.searchParams.get('k') !== ck) return new Response('no', { status: 401 });
    // شکست باید دیده شود: اگر گزارش یا پشتیبان بیفتد، cron نباید «ok» بگوید،
    // وگرنه جمعه‌شبی که گزارش نیامده در سابقه‌ی زمان‌بند «موفق» ثبت می‌شود.
    const failed: string[] = [];
    try { const rep = await buildWeeklyReport(); await notifyAdmins(rep); }
    catch (e) { console.error('weekly report failed', e); failed.push('report'); }
    try {
      const { data: admins } = await supabase.from('bot_admins').select('chat_id').limit(1);
      if (admins && admins.length) await sendBackup(Number(admins[0].chat_id));
    } catch (e) { console.error('weekly backup failed', e); failed.push('backup'); }
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
        for (const it of cart) { tot += it.quantity * it.unit_price; sm += `• ${escH(it.name)} × ${fa(it.quantity)} = ${fa(it.quantity * it.unit_price)} ت\n`; }
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
        await sendProductVideo(chatId, data.slice(4), 'jin');
      } else if (data.startsWith('crt_')) {
        await sendProductVideo(chatId, data.slice(4), 'carton');
      } else if (data.startsWith('pics_')) {
        await sendProductPhotos(chatId, data.slice(5));
      } else if (data.startsWith('size_')) {
        const pid = data.slice(5);
        const { data: p } = await supabase.from('products').select('name,size_info').eq('id', pid).maybeSingle();
        if (p && p.size_info && String(p.size_info).trim()) {
          await send(chatId, `📏 <b>اندازه و قواره «${escH(p.name)}»:</b>\n${escH(p.size_info)}`);
        } else {
          await send(chatId, '📏 اطلاعاتِ اندازه‌ی این کالا هنوز ثبت نشده 🙏');
        }
      } else if (data.startsWith('paynow_')) {
        const oid = data.slice(7);
        const { data: ord } = await supabase.from('telegram_orders').select('id,total,card_file_id,paid_confirmed_at,customer_name,customer_phone').eq('id', oid).maybeSingle();
        if (!ord) {
          await send(chatId, 'این سفارش پیدا نشد 🙏');
        } else if (ord.paid_confirmed_at) {
          await send(chatId, '✅ پرداختِ این سفارش قبلاً تأیید شده 🌹');
        } else if (ord.card_file_id) {
          await sendPhoto(chatId, ord.card_file_id, `💳 مبلغِ <b>${fa(ord.total)} تومان</b> رو به این کارت واریز کن.\n\nبعدِ واریز، <b>عکسِ فیش</b> رو همین‌جا بفرست 🙏`);
          await setSession(chatId, { step: 'awaiting_receipt', temp_order_id: ord.id });
        } else {
          await send(chatId, '💳 چند لحظه صبر کن — الان شماره‌کارت رو برات می‌فرستیم 🌹');
          const { data: admins } = await supabase.from('bot_admins').select('chat_id');
          const req2 = `🔔 <b>مشتری می‌خواد پرداخت کنه</b>\n👤 ${escH(ord.customer_name || '')}\n📞 ${escH(ord.customer_phone || '')}\n💰 مبلغ: <b>${fa(ord.total)} تومان</b>\n\n📸 <b>عکسِ کارتی که می‌خوای بهش واریز کنه رو بفرست.</b>`;
          for (const a of (admins || [])) {
            try {
              await getSession(Number(a.chat_id));
              await setSession(Number(a.chat_id), { step: 'awaiting_card', temp_order_id: ord.id });
              await send(Number(a.chat_id), req2);
            } catch (_) {}
          }
        }
      } else if (data.startsWith('sendcard_')) {
        if (await isAdmin(chatId)) {
          const oid = data.slice(9);
          const { data: ord } = await supabase.from('telegram_orders').select('id,total').eq('id', oid).maybeSingle();
          if (!ord) {
            await send(chatId, 'این سفارش پیدا نشد 🙏');
          } else {
            await setSession(chatId, { step: 'awaiting_card', temp_order_id: ord.id });
            await send(chatId, `📸 عکسِ کارتی که می‌خوای مشتری مبلغِ <b>${fa(ord.total)} تومان</b> رو بهش واریز کنه بفرست.`);
          }
        }
      } else if (data.startsWith('paid_')) {
        if (await isAdmin(chatId)) {
          const oid = data.slice(5);
          const { data: ord } = await supabase.from('telegram_orders').select('id,tg_user_id,total').eq('id', oid).maybeSingle();
          if (ord) {
            await supabase.from('telegram_orders').update({ paid_confirmed_at: new Date().toISOString() }).eq('id', ord.id);
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
              for (const it of cart) sm += `• ${escH(it.name)} × ${fa(it.quantity)} = ${fa(it.quantity * it.unit_price)} ت\n`;
              sm += `<b>جمعِ کل: ${fa(total)} تومان</b>`;
              if (ord.note) sm += '\n\n(کدِ تخفیفِ قبلی برداشته شد)';
              await send(chatId, sm, { inline_keyboard: [[{ text: '💳 می‌خوام پرداخت کنم', callback_data: `paynow_${ord.id}` }], [{ text: '✏️ ویرایشِ دوباره', callback_data: `edit_${ord.id}` }]] });
              try {
                const { data: admins } = await supabase.from('bot_admins').select('chat_id');
                let am = `🔄 <b>مشتری سفارشش رو ویرایش کرد</b>\n👤 ${escH(s.customer_name || '')}\n📞 ${escH(s.customer_phone || '')}\n\n`;
                for (const it of cart) am += `• ${escH(it.name)} × ${fa(it.quantity)} = ${fa(it.quantity * it.unit_price)} ت\n`;
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
        await send(chatId, 'چند عدد می‌خوای؟ (یه عدد بفرست، مثلاً ۵)');
      } else if (data.startsWith('p_')) {
        await showProductDetail(chatId, data.slice(2));
      } else if (data === 'done_items') {
        if (s.editing_order_id) { await setSession(chatId, { step: 'edit_cart' }); await showEditCart(chatId); return new Response('ok'); }
        const cart = s.cart || [];
        if (cart.length === 0) {
          await send(chatId, 'هنوز چیزی انتخاب نکردی 🙂');
          await showProducts(chatId);
        } else {
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
          const { data: ord } = await supabase.from('telegram_orders').select('id,tg_user_id,total').eq('id', ps.temp_order_id).maybeSingle();
          await setSession(chatId, { step: 'idle', temp_order_id: null });
          if (!ord) { await send(chatId, 'سفارش پیدا نشد 🙏'); return new Response('ok'); }
          if (!ord.tg_user_id) { await send(chatId, 'چتِ مشتریِ این سفارش ثبت نشده 🙏'); return new Response('ok'); }
          await sendPhoto(Number(ord.tg_user_id), pic.file_id, `💳 مبلغِ <b>${fa(ord.total)} تومان</b> رو به این کارت واریز کن.\n\nبعدِ واریز، <b>عکسِ فیش</b> رو همین‌جا بفرست 🙏`);
          await supabase.from('telegram_orders').update({ card_file_id: pic.file_id, card_sent_at: new Date().toISOString() }).eq('id', ord.id);
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
          await send(chatId, '✅ کارت برای مشتری رفت.', { inline_keyboard: [[{ text: '✅ پرداخت شد (تأیید به مشتری)', callback_data: `paid_${ord.id}` }]] });
          return new Response('ok');
        }
        if (ps.step === 'awaiting_receipt' && ps.temp_order_id) {
          const { data: ord } = await supabase.from('telegram_orders').select('id,total,customer_name,customer_phone,customer_city').eq('id', ps.temp_order_id).maybeSingle();
          await setSession(chatId, { step: 'idle', temp_order_id: null });
          if (!ord) { await send(chatId, 'سفارشت پیدا نشد 🙏'); return new Response('ok'); }
          await supabase.from('telegram_orders').update({ receipt_file_id: pic.file_id, receipt_sent_at: new Date().toISOString() }).eq('id', ord.id);
          await send(chatId, '🧾 فیشت رسید، ممنون! بررسیش می‌کنیم 🌹');
          try {
            const { data: admins } = await supabase.from('bot_admins').select('chat_id');
            const cap = `🧾 <b>فیشِ واریزی رسید</b>\n👤 ${escH(ord.customer_name || '')}\n📞 ${escH(ord.customer_phone || '')}\n🏙 ${escH(ord.customer_city || '')}\n💰 مبلغِ سفارش: <b>${fa(ord.total)} تومان</b>`;
            for (const a of (admins || [])) {
              try { await sendPhoto(Number(a.chat_id), pic.file_id, cap, { inline_keyboard: [[{ text: '✅ پرداخت شد (تأیید به مشتری)', callback_data: `paid_${ord.id}` }]] }); } catch (_) {}
            }
          } catch (_) {}
          return new Response('ok');
        }
        if (ps.step === 'asking') { await forwardQuestion(chatId, msg, msg.caption || '', pic.file_id); return new Response('ok'); }
        if (await isAdmin(chatId)) {
          await send(chatId, 'عکسِ کالاها رو از خودِ پنل اضافه کن 🙏');
        }
        return new Response('ok');
      }

      const vid = msg.video || (msg.document && /video/.test(msg.document.mime_type || '') ? msg.document : null);
      if (vid) {
        const vs = await getSession(chatId);
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

        if (cmdA === '/start') { await showMain(chatId); return new Response('ok'); }
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
          if (!qty || qty <= 0) { await send(chatId, 'یه عددِ درست بفرست (مثلاً ۳)'); return new Response('ok'); }
          const { data: prod } = await supabase.from('products').select('id,name,price').eq('id', s.temp_product_id).maybeSingle();
          if (!prod) { await setSession(chatId, { temp_product_id: null, step: 'choosing' }); await send(chatId, 'این کالا دیگه تو لیست نیست 🙏'); await showProducts(chatId); return new Response('ok'); }
          const cart = s.cart || [];
          cart.push({ product_id: prod.id, name: prod.name, quantity: qty, unit_price: Number(prod.price) });
          if (s.editing_order_id) {
            await setSession(chatId, { cart, temp_product_id: null, step: 'edit_cart' });
            await send(chatId, `«${escH(prod.name)}» × ${fa(qty)} اضافه شد ✅`);
            await showEditCart(chatId);
          } else {
            await setSession(chatId, { cart, temp_product_id: null });
            await send(chatId, `«${escH(prod.name)}» × ${fa(qty)} اضافه شد ✅`);
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
          const fb: any = found.map((p: any) => [{ text: `${p.name} — ${fa(p.price)} ت`, callback_data: `p_${p.id}` }]);
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
    console.error(e);
    return new Response('ok');
  }
});
