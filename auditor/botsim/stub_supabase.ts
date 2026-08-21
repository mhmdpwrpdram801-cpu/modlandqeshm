/* استابِ supabase-js برای شبیه‌سازِ ربات.
 *
 * فقط همان متدهایی را دارد که bot/index.ts واقعاً صدا می‌زند — شمرده شد:
 * select ۴۲ · eq ۳۳ · maybeSingle ۲۱ · update ۹ · limit ۸ · order ۴ · single ۲
 * insert ۲ · ilike ۲ · gte ۲ · range ۱ · not ۱ · storage.remove ۱
 *
 * قاعده‌ی TEST-05: شبیه‌ساز خودش وارسی می‌خواهد. اگر متدی صدا زده شود که اینجا
 * نیست، **بلند خطا می‌دهد** — چون استابی که بی‌صدا undefined برگرداند، حالتی
 * می‌سازد که در دیتابیسِ واقعی ممکن نیست و «باگ»هایی می‌سازد که وجود ندارند.
 */

export type Row = Record<string, unknown>;
export const DB: Record<string, Row[]> = {};
// خرابیِ دیتابیس را می‌شود عمداً روشن کرد — بدونِ آن، مسیرِ سلامت فقط در حالتِ
// خوب سنجیده می‌شود و «۵۰۳ می‌دهد یا نه» هیچ‌وقت معلوم نمی‌شود.
export const FAULT = { on: false };
export const CALLS: string[] = [];

/* جدول‌های واقعیِ دیتابیس — `auditor/schema.txt` منبعش است.
 *
 * تا امروز استاب هر نامی را قبول می‌کرد (`DB[table] ??= []`)، یعنی اگر ربات در
 * نامِ جدول یک حرف اشتباه می‌نوشت — یا به جدولی می‌نوشت که اصلاً ساخته نشده —
 * شبیه‌ساز **سبز** می‌داد و روی تولید داده بی‌صدا گم می‌شد. سخت‌گیری روی فیلتر و
 * `rpc` بود ولی روی نامِ جدول نبود؛ همان سبزِ توخالیِ CORE-12، یک لایه پایین‌تر.
 */
export const TABLES = new Set([
  "bot_admins", "bot_events", "customer_balances", "customers", "dev_tests",
  "discount_codes", "expenses", "invoice_items", "invoices", "payments",
  "products", "quotes", "returns", "salaries", "settings", "shipments",
  "telegram_orders", "telegram_sessions", "employees", "app_config",
  "client_errors",
]);

/* قیدهای CHECK که دیتابیسِ واقعی دارد و اینجا هم باید همان‌طور رد شوند.
 * وگرنه یک نامِ رویدادِ غلط در ربات، در شبیه‌ساز بی‌صدا می‌نشیند و فقط روی تولید
 * ردش می‌شود — جایی که هیچ‌کس نگاه نمی‌کند.
 * `auditor/server_audit.py` این فهرست را با خودِ `bot/index.ts` و با عکسِ
 * ثابت‌های دیتابیس مقابله می‌کند تا از هم دور نیفتند (TEST-05). */
export const BOT_EVENTS = [
  "start", "browse", "view", "media", "cart_add", "checkout",
  "order", "pay_click", "receipt", "paid", "ask",
];

function checkConstraints(table: string, row: Row) {
  if (table === "bot_events") {
    if (!BOT_EVENTS.includes(String(row.event))) {
      throw new Error(`استابِ supabase: قیدِ bot_events_event_known — رویدادِ ناشناخته «${row.event}»`);
    }
    if (row.chat_id == null) {
      throw new Error("استابِ supabase: bot_events.chat_id نمی‌تواند خالی باشد");
    }
  }
}

function match(row: Row, f: [string, string, unknown][]): boolean {
  return f.every(([op, col, val]) => {
    const v = row[col];
    if (op === "eq") return String(v ?? "") === String(val ?? "");
    if (op === "neq") return String(v ?? "") !== String(val ?? "");
    if (op === "gte") return String(v ?? "") >= String(val ?? "");
    if (op === "not") return v !== val;
    if (op === "ilike") {
      const pat = String(val).replace(/%/g, "").toLowerCase();
      return String(v ?? "").toLowerCase().includes(pat);
    }
    throw new Error(`استابِ supabase: فیلترِ پشتیبانی‌نشده «${op}» — اضافه‌اش کن`);
  });
}

class Query implements PromiseLike<{ data: unknown; error: unknown }> {
  private filters: [string, string, unknown][] = [];
  private _limit: number | null = null;
  private _order: { col: string; asc: boolean } | null = null;
  private _range: [number, number] | null = null;
  private _mode: "select" | "insert" | "update" = "select";
  private _payload: Row | Row[] | null = null;
  private _one: "none" | "maybe" | "single" = "none";

  constructor(private table: string) {}

  select(_cols?: string) { CALLS.push(`${this.table}.select`); return this; }
  insert(p: Row | Row[]) { this._mode = "insert"; this._payload = p; return this; }
  update(p: Row) { this._mode = "update"; this._payload = p; return this; }
  eq(c: string, v: unknown) { this.filters.push(["eq", c, v]); return this; }
  neq(c: string, v: unknown) { this.filters.push(["neq", c, v]); return this; }
  gte(c: string, v: unknown) { this.filters.push(["gte", c, v]); return this; }
  ilike(c: string, v: unknown) { this.filters.push(["ilike", c, v]); return this; }
  not(c: string, _op: string, v: unknown) { this.filters.push(["not", c, v]); return this; }
  order(c: string, o?: { ascending?: boolean }) { this._order = { col: c, asc: o?.ascending !== false }; return this; }
  limit(n: number) { this._limit = n; return this; }
  range(a: number, b: number) { this._range = [a, b]; return this; }
  maybeSingle() { this._one = "maybe"; return this; }
  single() { this._one = "single"; return this; }

  private run() {
    if (FAULT.on) return { data: null, error: { message: 'شبیه‌ساز: خرابیِ عمدیِ دیتابیس' } };
    if (!TABLES.has(this.table)) {
      throw new Error(`استابِ supabase: جدولِ ناشناخته «${this.table}» — یا در دیتابیس نیست، یا نامش را در stub_supabase.ts اضافه کن`);
    }
    const rows = DB[this.table] ??= [];
    if (this._mode === "insert") {
      const add = Array.isArray(this._payload) ? this._payload : [this._payload!];
      add.forEach((r) => checkConstraints(this.table, r));
      const made = add.map((r) => ({ id: r.id ?? `gen-${this.table}-${rows.length + 1}`, ...r }));
      rows.push(...made);
      return { data: made, error: null };
    }
    let out = rows.filter((r) => match(r, this.filters));
    if (this._mode === "update") {
      out.forEach((r) => Object.assign(r, this._payload));
      return { data: out, error: null };
    }
    if (this._order) {
      const { col, asc } = this._order;
      out = [...out].sort((a, b) =>
        (String(a[col] ?? "") < String(b[col] ?? "") ? -1 : 1) * (asc ? 1 : -1));
    }
    if (this._range) out = out.slice(this._range[0], this._range[1] + 1);
    if (this._limit != null) out = out.slice(0, this._limit);
    if (this._one !== "none") {
      if (out.length === 0) {
        if (this._one === "single") return { data: null, error: { message: "no rows" } };
        return { data: null, error: null };
      }
      return { data: out[0], error: null };
    }
    return { data: out, error: null };
  }

  then<A, B>(res?: ((v: { data: unknown; error: unknown }) => A | PromiseLike<A>) | null,
             rej?: ((e: unknown) => B | PromiseLike<B>) | null): PromiseLike<A | B> {
    return Promise.resolve(this.run()).then(res, rej);
  }
}

export function createClient(_url: string, _key: string) {
  return {
    from(table: string) { return new Query(table); },
    storage: {
      from(_b: string) {
        return { remove: (paths: string[]) => { CALLS.push(`storage.remove:${paths.length}`); return Promise.resolve({ data: null, error: null }); } };
      },
    },
    auth: {
      getUser(_jwt: string) {
        return Promise.resolve({ data: { user: { id: "test-user" } }, error: null });
      },
    },
    rpc(name: string) {
      throw new Error(`استابِ supabase: rpc(${name}) پیاده نشده — اگر ربات صدایش می‌زند اضافه‌اش کن`);
    },
  };
}
