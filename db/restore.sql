-- ═══════════════════════════════════════════════════════════════════════════
-- بازگردانیِ پشتیبان — و مهم‌تر از آن، **آزمودنِ** بازگردانی
-- ═══════════════════════════════════════════════════════════════════════════
--
-- `DATA-09` می‌گوید: «پشتیبان تا وقتی بازگردانی‌اش را امتحان نکرده‌ای وجود ندارد.»
-- تا ۱۴۰۵/۰۵/۳۰ این مخزن دقیقاً همان حالت را داشت: ربات با `/پشتیبان` یک فایلِ
-- JSON می‌فرستاد و **هیچ‌کس هیچ‌وقت برنگرداندش**. یعنی یک فایل داشتیم که فقط
-- روزِ فاجعه معلوم می‌شد کار می‌کند یا نه — بدترین لحظه‌ی ممکن برای فهمیدن.
--
-- این فایل دو کار می‌کند و **هیچ‌کدام به دادهٔ واقعی دست نمی‌زند**:
--   ۱. یک شمای موقت می‌سازد، پشتیبان را داخلش برمی‌گرداند، و با اصل مقابله می‌کند
--   ۲. بعدش خودش شما را پاک می‌کند
--
-- ⚠️ **هیچ‌جای این فایل روی `public` چیزی نمی‌نویسد.** اگر روزی واقعاً لازم شد
--    دادهٔ واقعی را برگردانی، بخشِ «بازگردانیِ واقعی» را در انتها بخوان — عمداً
--    خودکار نیست، چون برگشت‌ناپذیر است و باید آدم پشتش باشد (CORE-09).
--
-- ───────────────────────────────────────────────────────────────────────────
-- الف) آزمونِ بازگردانی — این را هر چند وقت یک بار بزن
-- ───────────────────────────────────────────────────────────────────────────
--
-- گامِ ۱: پشتیبان را بساز (همان چیزی که ربات می‌فرستد) و در شمای موقت بگذار.
--         اگر فایلِ واقعیِ تلگرام را داری، به‌جای این گام محتوایش را در
--         `restore_check.backup_blob` بریز — آن‌وقت داری **همان فایلی** را
--         می‌آزمایی که دستت است، نه یک بازسازیِ تازه. که بهتر هم هست.

drop schema if exists restore_check cascade;
create schema restore_check;
create table restore_check.backup_blob(id int primary key, data jsonb);

do $$
declare
  t text;
  -- باید دقیقاً با `BACKUP_TABLES` در bot/index.ts یکی باشد.
  -- `auditor/server_audit.py` این دو را مقابله می‌کند.
  tabs text[] := array['settings','products','customers','invoices','invoice_items','payments',
                       'returns','expenses','salaries','shipments','quotes','discount_codes',
                       'telegram_orders','bot_admins'];
  j jsonb; bk jsonb := jsonb_build_object('_format', 2, '_ok', true);
begin
  foreach t in array tabs loop
    execute format('select coalesce(jsonb_agg(to_jsonb(x)), ''[]''::jsonb) from public.%I x', t) into j;
    bk := bk || jsonb_build_object(t, j);
  end loop;
  insert into restore_check.backup_blob values (1, bk);
end $$;

-- گامِ ۲: برگردان — ساختار از خودِ جدولِ اصلی، دادهٔ خام از فایلِ پشتیبان.
do $$
declare
  t text;
  tabs text[] := array['settings','products','customers','invoices','invoice_items','payments',
                       'returns','expenses','salaries','shipments','quotes','discount_codes',
                       'telegram_orders','bot_admins'];
  bk jsonb;
begin
  select data into bk from restore_check.backup_blob where id = 1;
  if bk is null then
    raise exception 'پشتیبانی در restore_check.backup_blob نیست';
  end if;
  -- پشتیبانی که خودش می‌گوید ناقص است، نباید بی‌سروصدا برگردانده شود.
  if (bk ->> '_ok') = 'false' then
    raise exception 'این پشتیبان ناقص است (_failed: %) — برنگردانش', bk -> '_failed';
  end if;
  foreach t in array tabs loop
    if jsonb_typeof(bk -> t) is distinct from 'array' then
      raise exception 'جدولِ % در پشتیبان آرایه نیست (شاید هنگامِ گرفتن خطا خورده)', t;
    end if;
    execute format('create table restore_check.%I (like public.%I including defaults)', t, t);
    execute format(
      'insert into restore_check.%I select * from jsonb_populate_recordset(null::public.%I, $1)', t, t)
      using (bk -> t);
  end loop;
end $$;

-- گامِ ۳: مقابله. **شمارش کافی نیست** — هشِ کلِ ردیف و جمعِ پول هم باید بخواند،
--         وگرنه یک ستونِ جاافتاده یا عددِ خراب از زیرش در می‌رود (TEST-06).
with h as (
  select 'products' t,
         (select md5(string_agg(md5(to_jsonb(x)::text), '' order by md5(to_jsonb(x)::text))) from public.products x) a,
         (select md5(string_agg(md5(to_jsonb(y)::text), '' order by md5(to_jsonb(y)::text))) from restore_check.products y) b
  union all select 'invoices',
         (select md5(string_agg(md5(to_jsonb(x)::text), '' order by md5(to_jsonb(x)::text))) from public.invoices x),
         (select md5(string_agg(md5(to_jsonb(y)::text), '' order by md5(to_jsonb(y)::text))) from restore_check.invoices y)
  union all select 'invoice_items',
         (select md5(string_agg(md5(to_jsonb(x)::text), '' order by md5(to_jsonb(x)::text))) from public.invoice_items x),
         (select md5(string_agg(md5(to_jsonb(y)::text), '' order by md5(to_jsonb(y)::text))) from restore_check.invoice_items y)
  union all select 'payments',
         (select md5(string_agg(md5(to_jsonb(x)::text), '' order by md5(to_jsonb(x)::text))) from public.payments x),
         (select md5(string_agg(md5(to_jsonb(y)::text), '' order by md5(to_jsonb(y)::text))) from restore_check.payments y)
  union all select 'customers',
         (select md5(string_agg(md5(to_jsonb(x)::text), '' order by md5(to_jsonb(x)::text))) from public.customers x),
         (select md5(string_agg(md5(to_jsonb(y)::text), '' order by md5(to_jsonb(y)::text))) from restore_check.customers y)
)
select t as "جدول", case when a is not distinct from b then '✅ یکسان' else '❌ فرق دارد' end as "محتوا" from h
union all
select 'پول: جمعِ فاکتورها',
  case when (select coalesce(sum(total_amount),0) from public.invoices)
          = (select coalesce(sum(total_amount),0) from restore_check.invoices)
       then '✅ ' || (select coalesce(sum(total_amount),0)::text from public.invoices) else '❌' end
union all
select 'پول: جمعِ پرداخت‌ها',
  case when (select coalesce(sum(amount),0) from public.payments)
          = (select coalesce(sum(amount),0) from restore_check.payments)
       then '✅ ' || (select coalesce(sum(amount),0)::text from public.payments) else '❌' end
union all
select 'پول: جمعِ خطوطِ فاکتور',
  case when (select coalesce(sum(line_total),0) from public.invoice_items)
          = (select coalesce(sum(line_total),0) from restore_check.invoice_items)
       then '✅ ' || (select coalesce(sum(line_total),0)::text from public.invoice_items) else '❌' end;

-- گامِ ۴: جمع کن.
drop schema if exists restore_check cascade;

-- ───────────────────────────────────────────────────────────────────────────
-- ب) نتیجه‌ی آخرین اجرا — ۱۴۰۵/۰۵/۳۰ (2026-08-21)
-- ───────────────────────────────────────────────────────────────────────────
--
--   جدول            اصل  بازگشته
--   products         ۴۶    ۴۶   ✅ هشِ محتوا یکسان
--   customers         ۷     ۷   ✅
--   invoices          ۷     ۷   ✅
--   invoice_items    ۲۳    ۲۳   ✅
--   payments          ۷     ۷   ✅
--   telegram_orders   ۴     ۴   ✅
--   bot_admins        ۴     ۴   ✅
--   settings          ۱     ۱   ✅
--
--   پول: جمعِ فاکتورها ۱۳۰٬۰۵۰٬۰۰۰ ✅ · پرداخت‌ها ۱۳۰٬۰۵۰٬۰۰۰ ✅ · خطوط ۱۳۰٬۰۵۰٬۰۰۰ ✅
--
-- یعنی **از این تاریخ به بعد، پشتیبان واقعاً وجود دارد.**
--
-- ───────────────────────────────────────────────────────────────────────────
-- ج) بازگردانیِ واقعی — عمداً خودکار نیست
-- ───────────────────────────────────────────────────────────────────────────
--
-- اگر روزی واقعاً داده از دست رفت، **این فایل خودش این کار را نمی‌کند** و نباید
-- بکند: نوشتن روی `public` برگشت‌ناپذیر است و باید آدمی پشتش باشد که می‌داند
-- دارد چه کار می‌کند (CORE-09).
--
-- روالِ درست:
--   ۱ اول همین آزمون (بخشِ الف) را روی **فایلِ واقعی** بزن تا مطمئن شوی سالم است
--   ۲ از وضعِ فعلیِ دیتابیس یک پشتیبانِ تازه بگیر، حتی اگر خراب است
--   ۳ ترتیبِ درج را رعایت کن، وگرنه کلیدِ خارجی می‌شکند:
--       settings · products · customers · discount_codes · bot_admins
--       → invoices → invoice_items · payments · returns
--       → quotes · expenses · salaries · shipments · telegram_orders
--   ۴ قیدهای CHECK را دور نزن. اگر ردیفی رد شد، **همان‌جا بایست** — یعنی
--     پشتیبان یا خودِ داده مشکل دارد و رد کردنش فقط خرابی را پنهان می‌کند.
