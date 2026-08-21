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
  try { payload = init?.body ? JSON.parse(String(init.body)) : {}; } catch { /* بدنه‌ی غیرِ JSON */ }
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
const CART = [
  { product_id: "p1", name: "شلوار", quantity: 3, unit_price: 850000 },
  { product_id: "p2", name: "شومیز", quantity: 2, unit_price: 420000 },
];
reset({ step: "address", cart: CART, customer_name: "حاج رضا", customer_phone: "0912", customer_city: "قشم" });
await send(msg("خیابان اول، پلاک ۲"));
check("جمع بدونِ تخفیف", DB.telegram_orders[0]?.total, 3390000);

// ── ۲) تخفیفِ درصدی ─────────────────────────────────────────────────────────
// ۳٬۳۹۰٬۰۰۰ × ۰٫۹ = ۳٬۰۵۱٬۰۰۰
reset({ step: "address", cart: CART, customer_name: "x", customer_phone: "y", customer_city: "z", discount_pct: 10, discount_code: "OFF10" });
await send(msg("آدرس"));
check("تخفیفِ ۱۰٪", DB.telegram_orders[0]?.total, 3051000);

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

// ── ۵) نامِ بدقواره باید در پیامِ تلگرام فرار داده شود (SEC-04) ─────────────
console.log("\n━━━ فرارِ خروجی ━━━");
reset({ step: "address", cart: [{ product_id: "p1", name: "جین <b>۲۰۲۶</b> & \"ویژه\"", quantity: 1, unit_price: 100 }],
        customer_name: "علی <script>x</script>", customer_phone: "0912", customer_city: "قشم" });
await send(msg("آدرس"));
const texts = TG.filter((t) => t.method === "sendMessage").map((t) => String(t.payload.text)).join("\n");
check("تگِ خام در پیام نیست", /<b>۲۰۲۶<\/b>|<script>/.test(texts), false);
check("متنِ فرارداده‌شده هست", texts.includes("&lt;b&gt;") || texts.includes("&lt;script&gt;"), true);

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
await send(msg("۳"));
check("افزودن به سبد رویدادِ cart_add می‌سازد", evs().filter((e) => e === "cart_add").length, 1);
check("cart_add تعداد را نگه می‌دارد", DB.bot_events.find((e) => e.event === "cart_add")?.meta, { qty: 3, unit_price: 850000 });

// ثبتِ سفارش → `order` با جمعِ دستی‌حساب‌شده: ۳×۸۵۰٬۰۰۰ + ۲×۴۲۰٬۰۰۰ = ۳٬۳۹۰٬۰۰۰
reset({ step: "address", cart: CART, customer_name: "x", customer_phone: "y", customer_city: "z" });
await send(msg("آدرس"));
check("سفارش رویدادِ order با جمعِ درست می‌سازد",
  DB.bot_events.find((e) => e.event === "order")?.meta, { total: 3390000, items: 2 });

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

console.log("\n" + "═".repeat(52));
console.log(`  ${pass} بررسی پاس شد`);
if (fails.length) {
  console.log(`  ❌ ${fails.length} ایراد:`);
  for (const f of fails) console.log("     • " + f);
  Deno.exit(1);
}
console.log("  ✅ بدونِ ایراد");
