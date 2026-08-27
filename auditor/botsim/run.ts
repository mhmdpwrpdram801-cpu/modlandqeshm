/* شبیه‌سازِ تلگرام — تستِ رفتاریِ ربات.
 *
 * پنل ۱۰۰ بررسی دارد و ابزارِ خرج ۷۱؛ ربات تا امروز **صفر** داشت، با اینکه نهصد و
 * سی‌وهشت خط منطقِ پول‌محور دارد و تنها جایی است که غریبه‌ها مستقیم با آن حرف می‌زنند.
 *
 * اینجا **خودِ کدِ ربات** اجرا می‌شود، نه یک بازنویسیِ آن. فقط دنیای بیرون استاب
 * می‌شود: دیتابیس (stub_supabase.ts) و تلگرام (fetch). هیچ درخواستی به شبکه نمی‌رود.
 *
 *   /tmp/deno/bin/deno run -A --import-map auditor/botsim/import_map.json auditor/botsim/run.ts
 */
import { CALLS, DB, FAULT } from "./stub_supabase.ts";

// ── دنیای بیرون ─────────────────────────────────────────────────────────────
for (
  const [k, v] of [
    ["BOT_TOKEN", "test-token"],
    ["SUPABASE_URL", "https://example.invalid"],
    ["SUPABASE_SERVICE_ROLE_KEY", "test-key"],
    ["CRON_KEY", "test-cron"],
  ]
) Deno.env.set(k, v);

export const TG: { method: string; payload: Record<string, unknown> }[] = [];
let handler: ((r: Request) => Promise<Response>) | null = null;
// حجمی که استابِ تلگرام برای هر فیلم اعلام می‌کند؛ تست عوضش می‌کند تا بودجه پر شود.
let VID_BYTES = 1000;

// Deno.serve را می‌گیریم تا به‌جای باز کردنِ پورت، خودِ تابع دستمان بیاید.
(Deno as unknown as { serve: unknown }).serve = (h: (r: Request) => Promise<Response>) => {
  handler = h;
  return { finished: Promise.resolve(), shutdown: () => {} };
};

// هر تماسِ خروجی ثبت می‌شود و هیچ‌وقت به شبکه نمی‌رود. اگر آدرسی جز تلگرام
// صدا زده شود، بلند خطا می‌دهد — تستی که بی‌خبر به اینترنت بزند تستِ سالمی نیست.
globalThis.fetch = ((input: string | URL | Request, init?: RequestInit) => {
  const url = String(input instanceof Request ? input.url : input);
  if (!url.startsWith("https://api.telegram.org/")) {
    throw new Error(`شبیه‌ساز: تماسِ بیرونیِ غیرمنتظره → ${url}`);
  }
  const method = url.split("/").pop() || "?";
  let payload: Record<string, unknown> = {};
  // `sendDocument` و آپلودِ ویدیو با **FormData** می‌روند، نه JSON. استاب قبلاً
  // فقط JSON را می‌خواند، پس `payload` برای آن مسیرها همیشه `{}` بود — یعنی
  // هر بررسی‌ای که به کپشنشان نگاه می‌کرد **الکی سبز** می‌شد، چون رشته‌ی خالی
  // هیچ الگویی را تطابق نمی‌دهد. (همین‌جا لو رفت: بررسیِ «کپشنِ پشتیبان هشدار
  // ندارد» روی پشتیبانِ عمداً خراب هم سبز می‌ماند.)
  if (init?.body instanceof FormData) {
    for (const [k, v] of (init.body as FormData).entries()) {
      payload[k] = typeof v === "string" ? v : `[blob ${(v as Blob).size}]`;
    }
  } else {
    try { payload = init?.body ? JSON.parse(String(init.body)) : {}; } catch { /* بدنه‌ی غیرِ JSON */ }
  }
  TG.push({ method, payload });

  // دانلودِ خودِ فایل (مسیرِ /file/bot…) — این همان چیزی است که پهنای باند می‌برد.
  // اندازه‌اش را از VID_BYTES می‌گیریم تا بشود بودجه‌ی حجمی را در تست پر کرد.
  if (url.includes("/file/bot")) {
    return Promise.resolve(new Response(new Uint8Array(8), {
      status: 200,
      headers: { "Content-Type": "video/mp4", "Content-Length": String(VID_BYTES) },
    }));
  }
  if (method === "getFile") {
    return Promise.resolve(new Response(
      JSON.stringify({ ok: true, result: { file_path: "videos/f.mp4" } }),
      { headers: { "Content-Type": "application/json" } },
    ));
  }
  return Promise.resolve(new Response(
    JSON.stringify({ ok: true, result: { message_id: TG.length } }),
    { headers: { "Content-Type": "application/json" } },
  ));
}) as typeof fetch;

// مسیرِ ربات از محیط خوانده می‌شود تا بشود شبیه‌ساز را روی یک کپیِ جهش‌یافته زد.
// تستی که نشان ندهد می‌تواند قرمز شود، فقط یک سبزِ تزیینی است.
const BOT_PATH = Deno.env.get("BOT_SRC") ?? "../../bot/index.ts";
await import(BOT_PATH);
if (!handler) throw new Error("شبیه‌ساز: Deno.serve صدا زده نشد — ربات بالا نیامد");

// ── کمک‌ها ──────────────────────────────────────────────────────────────────
const CHAT = 555;
async function send(update: unknown) {
  const r = await handler!(new Request(
    "https://x/functions/v1/telegram-bot?secret=test-token",
    { method: "POST", body: JSON.stringify(update), headers: { "Content-Type": "application/json" } },
  ));
  await r.text();
  return r;
}
const msg = (text: string) => ({
  message: { chat: { id: CHAT }, from: { id: CHAT, username: "tester" }, text },
});

function reset(session: Record<string, unknown>) {
  TG.length = 0; CALLS.length = 0;
  for (const k of Object.keys(DB)) delete DB[k];
  DB.products = [
    { id: "p1", name: "شلوار جین آبی «ویژه» <b>۲۰۲۶</b> & کد A-1", price: 850000, active: true },
    { id: "p2", name: "شومیز طرح‌دار", price: 420000, active: true },
    { id: "p9", name: "دورس تو کرک P&C FLORIDA", price: 1350000, active: true },
  ];
  DB.bot_admins = [{ chat_id: 999 }];
  DB.discount_codes = [{ code: "OFF10", percent: 10, active: true }];
  DB.telegram_orders = [];
  DB.telegram_sessions = [{ chat_id: CHAT, ...session }];
}

let pass = 0; const fails: string[] = [];
function check(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log(`  ✅ ${name}`); }
  else { fails.push(`${name}: ${g} ≠ ${w}`); console.log(`  ❌ ${name}: ${g} ≠ انتظار ${w}`); }
}

// ── ۱) جمعِ سفارش بدونِ تخفیف، با عددِ دستی‌حساب‌شده ────────────────────────
// ۳ × ۸۵۰٬۰۰۰ + ۲ × ۴۲۰٬۰۰۰ = ۲٬۵۵۰٬۰۰۰ + ۸۴۰٬۰۰۰ = ۳٬۳۹۰٬۰۰۰
console.log("\n━━━ جمعِ سفارش ━━━");
// تعدادها عمداً ۶ و ۱۲ اند: از نسخه‌ی ۴۲ ربات تعدادِ دیگری نمی‌سازد، پس سبدی با
// ۳ عدد حالتی است که در دنیای واقعی ممکن نیست و شبیه‌ساز نباید بسازدش (TEST-05).
// ۶×۸۵۰٬۰۰۰ + ۱۲×۴۲۰٬۰۰۰ = ۵٬۱۰۰٬۰۰۰ + ۵٬۰۴۰٬۰۰۰ = ۱۰٬۱۴۰٬۰۰۰
const CART = [
  { product_id: "p1", name: "شلوار", quantity: 6, unit_price: 850000 },
  { product_id: "p2", name: "شومیز", quantity: 12, unit_price: 420000 },
];
reset({ step: "address", cart: CART, customer_name: "حاج رضا", customer_phone: "0912", customer_city: "قشم" });
await send(msg("خیابان اول، پلاک ۲"));
check("جمع بدونِ تخفیف", DB.telegram_orders[0]?.total, 10140000);

// ── ۲) تخفیفِ درصدی ─────────────────────────────────────────────────────────
// ۱۰٬۱۴۰٬۰۰۰ × ۰٫۹ = ۹٬۱۲۶٬۰۰۰
reset({ step: "address", cart: CART, customer_name: "x", customer_phone: "y", customer_city: "z", discount_pct: 10, discount_code: "OFF10" });
await send(msg("آدرس"));
check("تخفیفِ ۱۰٪", DB.telegram_orders[0]?.total, 9126000);

// ── ۳) تخفیفِ ۱۰۰٪ نباید منفی یا عجیب بدهد ─────────────────────────────────
reset({ step: "address", cart: CART, customer_name: "x", customer_phone: "y", customer_city: "z", discount_pct: 100, discount_code: "FREE" });
await send(msg("آدرس"));
check("تخفیفِ ۱۰۰٪ → صفر، نه منفی", DB.telegram_orders[0]?.total, 0);

// ── ۳.۵) درصدِ بالای ۱۰۰ نباید جمع را منفی کند ─────────────────────────────
// این مرز را جهش‌آزمایی لازم کرد: با دقیقاً ۱۰۰٪ حاصل صفرِ دقیق است و
// Math.max(0,…) با نبودنش یکی می‌شود، پس آن محافظ اصلاً سنجیده نمی‌شد.
// کدِ تخفیف از دیتابیس می‌آید؛ یک ردیفِ percent=150 کافی است تا منفی شود.
reset({ step: "address", cart: CART, customer_name: "x", customer_phone: "y", customer_city: "z", discount_pct: 150, discount_code: "BAD" });
await send(msg("آدرس"));
check("درصدِ ۱۵۰ → صفر، نه منفی", DB.telegram_orders[0]?.total, 0);

// ── ۴) سبدِ خالی نباید سفارش بسازد ──────────────────────────────────────────
reset({ step: "address", cart: [], customer_name: "x", customer_phone: "y", customer_city: "z" });
await send(msg("آدرس"));
check("سبدِ خالی سفارش نمی‌سازد", DB.telegram_orders.length, 0);

// ── ۴.۵) تعداد باید مضربِ ۶ باشد ────────────────────────────────────────────
// نیم‌جین ۶، جین ۱۲، جین‌ونیم ۱۸، دو جین ۲۴، دو جین‌ونیم ۳۰ … همه مضربِ ۶ اند.
// خواستِ مالک، به همین ترتیب: نیم‌جین، جینِ کامل، هر مضربِ ۱۲، و هر جینِ کاملی
// که یک نیم‌جین به آن اضافه شود.
// گفتنِ قاعده بدونِ اجرا کردنش بدتر از نگفتنش است: مشتری ۳ تا سفارش می‌دهد،
// سفارش ثبت می‌شود، و مالک باید زنگ بزند و درستش کند.
// مرزها عمداً هر دو طرفِ ۶ را می‌گیرند (۵ و ۷)، وگرنه یک سدِ «فقط ≥۶» هم سبز
// می‌شد بی‌آنکه مضرب بودن را بسنجد.
console.log("\n━━━ بسته‌بندیِ فروش ━━━");
for (const bad of ["۳", "۱", "۵", "۷", "۱۳", "۱۷", "۱۹", "۲۵"]) {
  reset({ step: "qty", cart: [], temp_product_id: "p1" });
  TG.length = 0;
  await send(msg(bad));
  const t = TG.filter((x) => x.method === "sendMessage").map((x) => String(x.payload.text)).join("\n");
  check(`تعدادِ ${bad} رد می‌شود`, (DB.telegram_sessions[0]?.cart || []).length, 0);
  check(`ارورِ ${bad} راهنما را نشان می‌دهد`, /۶ عدد/.test(t) && /۱۲ عدد/.test(t), true);
}
// عددِ غلطِ بالای ۶ باید نزدیک‌ترین‌های درست را پیشنهاد بدهد، وگرنه مشتری باید
// خودش حساب کند و همان‌جا رها می‌کند.
// ⚠️ عمداً ۵۰ آزموده می‌شود نه ۲۰: همسایه‌های ۲۰ (۱۸ و ۲۴) خودشان در متنِ راهنما
// هستند، پس آن بررسی حتی با برداشتنِ کلِ پیشنهاد هم سبز می‌مانْد — با جهشِ عمدی
// همین اتفاق افتاد. ۴۸ و ۵۴ هیچ‌جای دیگرِ پیام نیستند.
{
  reset({ step: "qty", cart: [], temp_product_id: "p1" });
  TG.length = 0;
  await send(msg("۵۰"));
  const t = TG.filter((x) => x.method === "sendMessage").map((x) => String(x.payload.text)).join("\n");
  check("ارورِ ۵۰ نزدیک‌ترین‌ها (۴۸ و ۵۴) را پیشنهاد می‌دهد", /۴۸/.test(t) && /۵۴/.test(t), true);
}
for (const ok of ["۶", "۱۲", "۱۸", "۲۴", "۳۰", "۳۶"]) {
  reset({ step: "qty", cart: [], temp_product_id: "p1" });
  await send(msg(ok));
  check(`تعدادِ ${ok} قبول می‌شود`, (DB.telegram_sessions[0]?.cart || []).length, 1);
}
// پیامِ پرسش هم باید همین را بگوید، وگرنه مشتری اول عددِ غلط می‌زند و بعد ارور می‌بیند.
reset({ step: "choosing", cart: [] });
TG.length = 0;
await send({ callback_query: { id: "9", data: "buy_p1", from: { id: CHAT }, message: { chat: { id: CHAT } } } });
{
  const t = TG.filter((x) => x.method === "sendMessage").map((x) => String(x.payload.text)).join("\n");
  check("پرسشِ تعداد خودش نیم‌جین و جین را می‌گوید", /۶ عدد/.test(t) && /۱۲ عدد/.test(t), true);
  // مالک صریح خواست عدد بگیرد نه تعدادِ جین، پس پیام باید همین را روشن بگوید.
  check("پرسشِ تعداد می‌گوید عدد بنویس نه جین", /نه تعدادِ جین/.test(t) && /۱۸/.test(t), true);
}

// ── ۵) نامِ بدقواره باید در پیامِ تلگرام فرار داده شود (SEC-04) ─────────────
console.log("\n━━━ فرارِ خروجی ━━━");
reset({ step: "address", cart: [{ product_id: "p1", name: "جین <b>۲۰۲۶</b> & \"ویژه\"", quantity: 1, unit_price: 100 }],
        customer_name: "علی <script>x</script>", customer_phone: "0912", customer_city: "قشم" });
await send(msg("آدرس"));
const texts = TG.filter((t) => t.method === "sendMessage").map((t) => String(t.payload.text)).join("\n");
check("تگِ خام در پیام نیست", /<b>۲۰۲۶<\/b>|<script>/.test(texts), false);
check("متنِ فرارداده‌شده هست", texts.includes("&lt;b&gt;") || texts.includes("&lt;script&gt;"), true);

// ── ۵.۵) نامِ لاتین نباید قیمت را از تهِ خط بکشد کنارِ نام ────────────────
// باگی که مالک گزارش کرد: «دورس تو کرک P&C FLORIDA — ۱٬۳۵۰٬۰۰۰ ت» روی گوشی
// طوری دیده می‌شد که قیمت می‌چسبید به نامِ فارسی و لاتین می‌رفت تهِ خط.
// ⚠️ رشته همیشه درست بوده — چیزی که غلط است ترتیبِ **دیداری** است، و هیچ
// بررسیِ رشته‌ای این را نمی‌گیرد. با مختصات در مرورگر اندازه‌گیری شد:
//   بدونِ ایزوله → فارسی ← قیمت ← انگلیسی   (غلط)
//   با ایزوله   → فارسی ← انگلیسی ← قیمت   (درست)
// شبیه‌ساز پیکسل ندارد، پس همان چیزی را می‌سنجد که علتِ ثابت‌شده است:
// نام باید یک واحدِ بسته‌ی FSI…PDI باشد و قیمت **بعد** از بسته‌شدنش بیاید.
console.log("\n━━━ چیدمانِ راست‌به‌چپ ━━━");
{
  const FSI = "⁨", PDI = "⁩";
  reset({ step: "idle", cart: [] });
  TG.length = 0;
  await send(msg("/start"));
  await send({ callback_query: { id: "b1", data: "catall", from: { id: CHAT }, message: { chat: { id: CHAT } } } });
  const labels: string[] = [];
  for (const t of TG) {
    const kb = (t.payload as any)?.reply_markup?.inline_keyboard;
    if (Array.isArray(kb)) for (const row of kb) for (const b of row) if (b?.text) labels.push(String(b.text));
  }
  const lat = labels.find((x) => x.includes("FLORIDA")) || "";
  check("دکمه‌ی کالای لاتین پیدا شد", lat !== "", true);
  check("نامِ لاتین در ایزوله بسته شده", lat.includes(FSI + "دورس تو کرک P&C FLORIDA" + PDI), true);
  // قیمت باید **بعد** از PDI بیاید، وگرنه ایزوله جای اشتباه گذاشته شده
  check("قیمت بعد از بسته‌شدنِ نام می‌آید", lat.indexOf(PDI) >= 0 && lat.indexOf("۱,۳۵۰,۰۰۰") > lat.indexOf(PDI), true);
  // و نامِ کاملاً فارسی هم باید همان رفتار را داشته باشد — استثنا نداریم
  const fars = labels.find((x) => x.includes("شومیز")) || "";
  check("نامِ فارسی هم ایزوله می‌شود", fars.includes(FSI + "شومیز طرح‌دار" + PDI), true);
}

// ── ۶) دستورِ مدیر برای غریبه کار نمی‌کند (SEC-03) ─────────────────────────
console.log("\n━━━ مجوز ━━━");
reset({ step: "idle", cart: [] });
await send(msg("/backup"));
check("غریبه پشتیبان نمی‌گیرد", TG.some((t) => t.method === "sendDocument"), false);

// ── ۷) و برای مدیر کار می‌کند — وگرنه بررسیِ بالا بی‌معنی است ──────────────
reset({ step: "idle", cart: [] });
DB.bot_admins = [{ chat_id: CHAT }];
await send(msg("/backup"));
check("مدیر پشتیبان می‌گیرد", TG.some((t) => t.method === "sendDocument" || t.method === "sendMessage"), true);

// ── ۸) نشانیِ ویدیو امضا می‌خواهد (SEC-02، SEC-03) ─────────────────────────
// `?media=` نمی‌تواند هدرِ Authorization بگیرد (پنل آن را در `<video src>`
// می‌گذارد). راهِ درون‌حافظه‌ای اندازه‌گیری شد و کار نمی‌کرد: هر درخواست یک
// ایزوله‌ی تازه می‌گیرد. پس محافظ یک ژتونِ کوتاه‌عمر در خودِ نشانی است.
console.log("\n━━━ نشانیِ امضاشده ━━━");
async function getMedia(qs: string) {
  const r = await handler!(new Request(
    `https://x/functions/v1/telegram-bot?media=p1&which=jin${qs}`,
    { method: "GET" },
  ));
  await r.arrayBuffer();
  return r.status;
}
async function mintTok(pid: string, which: string, auth: boolean) {
  const r = await handler!(new Request(
    `https://x/functions/v1/telegram-bot?mediatoken=${pid}&which=${which}`,
    { method: "GET", headers: auth ? { authorization: "Bearer user-jwt" } : {} },
  ));
  return { status: r.status, body: await r.json().catch(() => ({})) };
}

reset({ step: "idle", cart: [] });
DB.products[0].video_jin_fid = "fid-1";

// ۸.۱ غریبه نمی‌تواند ژتون بگیرد — وگرنه کلِ کار بی‌معنی است.
const anon = await mintTok("p1", "jin", false);
check("غریبه ژتون نمی‌گیرد", anon.status, 401);

// ۸.۲ کاربرِ واردشده می‌گیرد، و با آن ویدیو باز می‌شود.
const mine = await mintTok("p1", "jin", true);
check("کاربرِ واردشده ژتون می‌گیرد", mine.status, 200);
const TOK = String((mine.body as { tok?: string }).tok || "");
check("ژتونِ درست کار می‌کند", await getMedia(`&t=${TOK}`), 200);

// ۸.۲.۵ و نشانیِ **بی‌ژتون** هم رد می‌شود — این همان بستنِ در است. تا وقتی این
// قرمز باشد، هر غریبه‌ای که نشانی را داشته باشد ویدیو را می‌کشد.
check("نشانیِ بی‌ژتون رد می‌شود", await getMedia(""), 401);

// ۸.۳ ژتونِ دستکاری‌شده رد می‌شود. آخرین نویسه عوض می‌شود تا طول یکی بماند —
// وگرنه فقط بررسیِ طول ردش می‌کرد و امضا اصلاً سنجیده نمی‌شد.
const bad = TOK.slice(0, -1) + (TOK.slice(-1) === "0" ? "1" : "0");
check("ژتونِ دستکاری‌شده رد می‌شود", await getMedia(`&t=${bad}`), 401);

// ۸.۴ ژتونِ یک کالا روی کالای دیگر کار نمی‌کند، و ژتونِ «جین» روی «کارتن» هم نه.
DB.products[1].video_jin_fid = "fid-2";
const r2 = await handler!(new Request(
  `https://x/functions/v1/telegram-bot?media=p2&which=jin&t=${TOK}`, { method: "GET" }));
await r2.arrayBuffer();
check("ژتونِ کالای دیگر کار نمی‌کند", r2.status, 401);
const rC = await handler!(new Request(
  `https://x/functions/v1/telegram-bot?media=p1&which=carton&t=${TOK}`, { method: "GET" }));
await rC.arrayBuffer();
check("ژتونِ «جین» روی «کارتن» کار نمی‌کند", rC.status, 401);

// ۸.۵ ژتونِ منقضی رد می‌شود — بدونِ این، ژتونِ لو رفته تا ابد معتبر است.
const expTok = await (async () => {
  const m = await mintTok("p1", "jin", true);
  const t = String((m.body as { tok?: string }).tok || "");
  return t.replace(/^\d+/, String(Math.floor(Date.now() / 1000) - 10));
})();
check("ژتونِ منقضی رد می‌شود", await getMedia(`&t=${expTok}`), 401);

// ── ۹) مسیرِ سلامت (OPS-04) ────────────────────────────────────────────────
// «۲۰۰ می‌دهم پس سالمم» چیزی را ثابت نمی‌کند. بررسیِ آخر مهم‌ترین است: با
// دیتابیسِ خراب باید ۵۰۳ بدهد. بدونِ آن، این مسیر فقط می‌گفت «تابع بالاست».
console.log("\n━━━ سلامت ━━━");
reset({ step: "idle", cart: [] });
const hq = (k: string) => new Request(`https://x/functions/v1/telegram-bot?health=${k}`, { method: "GET" });

const hNo = await handler!(hq("wrong-key"));
await hNo.text();
check("سلامت بدونِ کلیدِ درست رد می‌شود", hNo.status, 401);

const hOk = await handler!(hq("test-cron"));
const hBody = await hOk.json().catch(() => ({}));
check("سلامت با کلید ۲۰۰ می‌دهد", hOk.status, 200);
check("سلامت واقعاً دیتابیس را می‌سنجد", (hBody as { db?: boolean }).db, true);

FAULT.on = true;
const hBad = await handler!(hq("test-cron"));
await hBad.text();
FAULT.on = false;
check("دیتابیسِ خراب → ۵۰۳، نه ۲۰۰", hBad.status, 503);

// ── ۹) قیفِ فروش — رویدادهایی که صفحه‌ی «بازدید و نرخِ تبدیل» از آن‌ها ساخته می‌شود
// این‌ها **رفتار** را می‌سنجند، نه وجودِ تابع: کاری که مشتری می‌کند باید دقیقاً
// همان رویدادی را بسازد که پنل انتظارش را دارد. بدونِ این، یک رویدادِ جاافتاده
// فقط به‌صورتِ «نرخِ تبدیلِ عجیب» دیده می‌شد — ماه‌ها بعد، بی‌آنکه کسی بفهمد چرا.
console.log("\n━━━ قیفِ فروش ━━━");
const evs = () => (DB.bot_events || []).map((e) => String(e.event));

// دیدنِ کارتِ کالا باید دقیقاً یک `view` با شناسه‌ی همان کالا بسازد.
reset({ step: "choosing", cart: [] });
await send({ callback_query: { id: "1", data: "p_p1", from: { id: CHAT }, message: { chat: { id: CHAT } } } });
check("دیدنِ کالا رویدادِ view می‌سازد", evs(), ["view"]);
check("view به همان کالا چسبیده", DB.bot_events[0]?.product_id, "p1");

// لیستِ کالاها → browse. اینجا `showCategory` صدا زده می‌شود، همان مسیری که
// همه‌ی راه‌های رسیدن به لیست از آن رد می‌شوند.
reset({ step: "idle", cart: [] });
await send({ callback_query: { id: "2", data: "catall", from: { id: CHAT }, message: { chat: { id: CHAT } } } });
check("لیستِ کالاها رویدادِ browse می‌سازد", evs(), ["browse"]);

// افزودن به سبد: عددِ تعداد که می‌رسد، نه لحظه‌ی فشردنِ «می‌خوامش».
reset({ step: "qty", cart: [], temp_product_id: "p1" });
await send(msg("۶"));
check("افزودن به سبد رویدادِ cart_add می‌سازد", evs().filter((e) => e === "cart_add").length, 1);
check("cart_add تعداد را نگه می‌دارد", DB.bot_events.find((e) => e.event === "cart_add")?.meta, { qty: 6, unit_price: 850000 });

// ثبتِ سفارش → `order` با جمعِ دستی‌حساب‌شده: ۶×۸۵۰٬۰۰۰ + ۱۲×۴۲۰٬۰۰۰ = ۱۰٬۱۴۰٬۰۰۰
reset({ step: "address", cart: CART, customer_name: "x", customer_phone: "y", customer_city: "z" });
await send(msg("آدرس"));
check("سفارش رویدادِ order با جمعِ درست می‌سازد",
  DB.bot_events.find((e) => e.event === "order")?.meta, { total: 10140000, items: 2 });

// سفارشی که **ثبت نشده** نباید رویدادِ order بسازد، وگرنه نرخِ تبدیل باد می‌کند.
reset({ step: "address", cart: [], customer_name: "x", customer_phone: "y", customer_city: "z" });
await send(msg("آدرس"));
check("سبدِ خالی رویدادِ order نمی‌سازد", evs().filter((e) => e === "order").length, 0);

// SEC-08: هیچ متنی از مشتری نباید در آمار بنشیند. `meta` فقط عدد می‌گیرد.
reset({ step: "address", cart: CART, customer_name: "علی <script>x</script>", customer_phone: "09171112233", customer_city: "قشم" });
await send(msg("خیابانِ اول، پلاکِ ۲"));
const dump = JSON.stringify(DB.bot_events || []);
check("هیچ متنِ مشتری در آمار نیست",
  /علی|script|09171112233|خیابان/.test(dump), false);

// آمار حق ندارد خرید را بخواباند: اگر نوشتنِ رویداد خطا بدهد، سفارش باید ثبت شود.
// (`logEvent` خطا را می‌بلعد — این بررسی همان را ثابت می‌کند، نه اینکه فرض کند.)
reset({ step: "address", cart: CART, customer_name: "x", customer_phone: "y", customer_city: "z" });
const realFrom = DB.bot_events;
Object.defineProperty(DB, "bot_events", {
  configurable: true,
  get() { throw new Error("شبیه‌ساز: خرابیِ عمدیِ آمار"); },
  set() {},
});
await send(msg("آدرس"));
Object.defineProperty(DB, "bot_events", { configurable: true, writable: true, value: realFrom });
check("خرابیِ آمار جلوی ثبتِ سفارش را نمی‌گیرد", DB.telegram_orders.length, 1);
// **و مهم‌تر از ردیفِ دیتابیس، پیامِ مشتری.** نسخه‌ی اولِ همین بررسی فقط
// `telegram_orders.length` را می‌دید و یک جهشِ عمدی از زیرش در رفت: چون سفارش
// *قبل* از رویداد ثبت می‌شود، پرتاب‌شدنِ خطا ردیف را خراب نمی‌کند — فقط هرچه
// **بعدش** بود را می‌خورد: تأییدیه‌ی مشتری و خبرِ مدیر. یعنی مشتری پول می‌داد و
// هیچ «ثبت شد» نمی‌دید. بررسی باید همان را بسنجد که واقعاً از دست می‌رود.
check("خرابیِ آمار تأییدیه‌ی مشتری را نمی‌خورد",
  TG.some((t) => t.method === "sendMessage" && String(t.payload.text).includes("سفارشت ثبت شد")), true);

// و خودِ استاب: نامِ رویدادِ ناشناخته باید همان‌جا بلند خطا بدهد، چون دیتابیسِ
// واقعی یک قیدِ CHECK دارد. استابی که این را قبول کند، غلطِ تایپی را تا تولید
// می‌برد (TEST-05).
reset({ step: "idle", cart: [] });
let stubCaught = false;
try {
  const { createClient } = await import("./stub_supabase.ts");
  await createClient("x", "y").from("bot_events").insert({ chat_id: 1, event: "brwse" });
} catch { stubCaught = true; }
check("استاب رویدادِ ناشناخته را رد می‌کند", stubCaught, true);

// ── ۱۰) پشتیبان — DATA-09
// «پشتیبان تا وقتی بازگردانی‌اش را امتحان نکرده‌ای وجود ندارد.» بازگردانی روی
// دیتابیسِ واقعی آزموده شد (db/restore.sql)؛ این‌جا چیزِ دیگری سنجیده می‌شود که
// همان‌قدر مهم است: **پشتیبانِ ناقص نباید شبیهِ پشتیبانِ کامل باشد.**
console.log("\n━━━ پشتیبان ━━━");
const bkDoc = () => TG.find((t) => t.method === "sendDocument");
const bkCap = () => String((bkDoc()?.payload as { caption?: string } | undefined)?.caption ?? "");

// حالتِ سالم
reset({ step: "idle", cart: [] });
DB.bot_admins = [{ chat_id: CHAT }];
DB.settings = [{ id: 1, shop_name: "مدلند" }];
await send(msg("/پشتیبان"));
check("پشتیبانِ سالم فرستاده می‌شود", !!bkDoc(), true);
// **اول ثابت کن کپشن اصلاً وجود دارد.** بدونِ این، بررسیِ بعدی روی رشته‌ی خالی
// هم سبز می‌شود — و دقیقاً همین شد: تا وقتی استاب FormData را نمی‌خواند، کپشن
// همیشه '' بود و «هشدار ندارد» حتی روی پشتیبانِ عمداً خراب هم پاس می‌داد.
check("کپشنِ پشتیبان واقعاً خوانده می‌شود", bkCap().includes("مدلند قشم"), true);
check("کپشنِ سالم هشدار ندارد", /ناقص|تکیه نکن/.test(bkCap()), false);

// حالتِ خراب: **یک** جدول نمی‌آید و بقیه می‌آیند — خطرناک‌ترین حالت، چون فایل
// سالم به‌نظر می‌رسد. نسخه‌ی قبلی دقیقاً همین را بی‌صدا رد می‌کرد.
reset({ step: "idle", cart: [] });
DB.bot_admins = [{ chat_id: CHAT }];
DB.products = [{ id: "p1", name: "شلوار", price: 100 }];
FAULT.table = "invoices";
await send(msg("/پشتیبان"));
FAULT.table = undefined;
check("جدولِ خراب کپشن را هشداردار می‌کند", /ناقص/.test(bkCap()), true);
check("کپشن می‌گوید به فایل تکیه نکن", /تکیه نکن/.test(bkCap()), true);
check("نامِ جدولِ خراب در کپشن می‌آید", /فاکتور/.test(bkCap()), true);

// ── ۱۱) گزارشِ هفتگی — تکه‌ای که تا امروز هیچ‌جا اجرا نمی‌شد
// مسیرِ cron فقط در تولید صدا زده می‌شد، پس اگر یک نامِ جدول در آن غلط بود،
// جمعه شب بی‌صدا می‌افتاد و تا دوشنبه کسی نمی‌فهمید.
console.log("\n━━━ گزارشِ هفتگی ━━━");
const cronReq = () => handler!(new Request(
  "https://x/functions/v1/telegram-bot?cron=weekly&k=test-cron", { method: "GET" }));
const weekly = () => TG.filter((t) => t.method === "sendMessage")
  .map((t) => String(t.payload.text)).join("\n");

reset({ step: "idle", cart: [] });
DB.bot_admins = [{ chat_id: CHAT }];
DB.invoices = [{ id: "i1", total_amount: 500000, status: "paid", created_at: new Date().toISOString() }];
DB.invoice_items = [{ invoice_id: "i1", product_name: "شلوار", quantity: 2, created_at: new Date().toISOString() }];
DB.customer_balances = [{ balance: 250000 }];
// سه نفر: یکی فقط دید، یکی سبد پر کرد، یکی خرید. پس تبدیل = ۱ از ۳ = ۳۳٫۳٪
DB.bot_events_public = [
  { chat_id: 11, event: "start", created_at: new Date().toISOString() },
  { chat_id: 12, event: "start", created_at: new Date().toISOString() },
  { chat_id: 12, event: "cart_add", created_at: new Date().toISOString() },
  { chat_id: 13, event: "start", created_at: new Date().toISOString() },
  { chat_id: 13, event: "order", created_at: new Date().toISOString() },
];
DB.bot_carts_open = [{ cart_total: 850000 }, { cart_total: 150000 }];
await (await cronReq()).text();
const wk = weekly();
check("گزارشِ هفتگی فرستاده می‌شود", wk.includes("گزارشِ هفتگیِ مدلند قشم"), true);
check("بخشِ ربات در گزارش هست", wk.includes("ربات این هفته"), true);
check("بازدیدکننده‌ی یکتا درست شمرده می‌شود", /بازدیدکننده: ۳/.test(wk), true);
// ۱ خریدار از ۳ بازدیدکننده = ۳۳٪ (گردشده — `fa()` عددِ صحیح می‌دهد)
check("نرخِ تبدیل با حسابِ دستی می‌خواند", /نرخِ تبدیل: ۳۳٪/.test(wk), true);
// ۸۵۰٬۰۰۰ + ۱۵۰٬۰۰۰ = ۱٬۰۰۰٬۰۰۰
check("جمعِ سبدهای رهاشده درست است", /۱,۰۰۰,۰۰۰ ت روش مونده/.test(wk), true);

// و اگر خواندنِ آمار بشکند، گزارش نباید صفرِ دروغ بدهد.
reset({ step: "idle", cart: [] });
DB.bot_admins = [{ chat_id: CHAT }];
DB.invoices = [];
FAULT.table = "bot_events_public";
await (await cronReq()).text();
FAULT.table = undefined;
const wk2 = weekly();
check("خرابیِ آمار گزارش را نمی‌خواباند", wk2.includes("گزارشِ هفتگیِ مدلند قشم"), true);
check("خرابیِ آمار صفرِ دروغ نمی‌دهد", /بازدیدکننده: ۰/.test(wk2), false);
check("خرابیِ آمار صریح گفته می‌شود", wk2.includes("خونده نشد"), true);

console.log("\n" + "═".repeat(52));
console.log(`  ${pass} بررسی پاس شد`);
if (fails.length) {
  console.log(`  ❌ ${fails.length} ایراد:`);
  for (const f of fails) console.log("     • " + f);
  Deno.exit(1);
}
console.log("  ✅ بدونِ ایراد");
