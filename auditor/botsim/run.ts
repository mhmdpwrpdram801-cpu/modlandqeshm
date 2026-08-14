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
import { CALLS, DB } from "./stub_supabase.ts";

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

console.log("\n" + "═".repeat(52));
console.log(`  ${pass} بررسی پاس شد`);
if (fails.length) {
  console.log(`  ❌ ${fails.length} ایراد:`);
  for (const f of fails) console.log("     • " + f);
  Deno.exit(1);
}
console.log("  ✅ بدونِ ایراد");
