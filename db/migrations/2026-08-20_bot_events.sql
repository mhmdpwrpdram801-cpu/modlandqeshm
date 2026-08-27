-- رویدادهای ربات — پایه‌ی صفحه‌ی «بازدید و نرخِ تبدیل» در پنل.
--
-- چرا این جدول لازم شد: مشتری از **ربات** خرید می‌کند، نه از سایت (پنل پشتِ ورود
-- است و فقط مالک واردش می‌شود). ولی از رفتارِ مشتری در ربات هیچ ردی نمی‌مانْد:
-- `telegram_sessions` جای هر نفر **یک ردیف** دارد که سرِ جا بازنویسی می‌شود و
-- حتی `created_at` ندارد. یعنی هیچ‌وقت نمی‌شد گفت «این هفته چند نفر آمدند و چند
-- نفرشان خریدند». این جدول همان تاریخچه است.
--
-- DATA-02: فقط **افزودن** است — هیچ ستون و جدولی حذف یا عوض نمی‌شود، پس
-- استقرارِ ربات و پنل می‌تواند بعد از این بیاید بدونِ لحظه‌ای خرابی.
-- SEC-08: هیچ متنِ پیامِ مشتری اینجا نمی‌آید. فقط «کی، چه کاری، روی کدام کالا».

create table if not exists public.bot_events (
  id          bigserial primary key,
  chat_id     bigint      not null,
  event       text        not null,
  product_id  uuid        null references public.products(id) on delete set null,
  meta        jsonb       null,
  created_at  timestamptz not null default now(),

  -- قیدِ صریح روی نامِ رویداد: پنل و ربات باید سرِ یک فهرست توافق داشته باشند.
  -- بدونِ این، یک غلطِ تایپی در ربات یک رویدادِ نامرئی می‌سازد که هیچ‌جا شمرده
  -- نمی‌شود و هیچ خطایی هم نمی‌دهد (API-07: در مرز رد کن، ترمیم نکن).
  constraint bot_events_event_known check (event in (
    'start',      -- وارد ربات شد
    'browse',     -- لیستِ کالاها را باز کرد
    'view',       -- کارتِ یک کالا را دید
    'media',      -- فیلم/عکس/اندازه‌ی همان کالا را خواست
    'cart_add',   -- گذاشت توی سبد
    'checkout',   -- گفت «تمومِ خرید»
    'order',      -- سفارش ثبت شد
    'pay_click',  -- دکمه‌ی پرداخت را زد
    'receipt',    -- فیش فرستاد
    'paid',       -- پرداختش تأیید شد
    'ask'         -- سؤال پرسید
  ))
);

create index if not exists bot_events_created_idx on public.bot_events (created_at desc);
create index if not exists bot_events_event_created_idx on public.bot_events (event, created_at desc);
create index if not exists bot_events_chat_created_idx on public.bot_events (chat_id, created_at desc);

alter table public.bot_events enable row level security;

-- پنل فقط می‌خوانَد. نوشتن کارِ ربات است که با نقشِ سرویس می‌رود و RLS را رد
-- می‌کند — یعنی هیچ مشتری‌ای نمی‌تواند رویدادِ جعلی بسازد و آمار را دستکاری کند.
-- الگویش همان `ro_invoices` است، نه `rw_*`.
drop policy if exists ro_bot_events on public.bot_events;
create policy ro_bot_events on public.bot_events
  for select to authenticated using (true);

-- ─────────────────────────────────────────────────────────────────────────
-- نمای عمومی — پنل **این** را می‌خواند، نه خودِ جدول را.
--
-- چرا: چهار `chat_id` در `bot_admins` هست و هر چهار خودِ مالک است. اگر گشت‌وگذارِ
-- خودش هم «بازدیدکننده» شمرده شود، نرخِ تبدیل بی‌معنی می‌شود — به‌خصوص حالا که
-- تعدادِ مشتری‌ها کم است و یک نفر می‌تواند کلِ عدد را جابه‌جا کند.
--
-- نما با اختیارِ **مالکِ نما** اجرا می‌شود (`security_invoker` خاموش)، پس می‌تواند
-- `bot_admins` را ببیند در حالی که همان جدول برای پنل بسته می‌مانَد.
create or replace view public.bot_events_public as
  select e.id, e.chat_id, e.event, e.product_id, e.meta, e.created_at
  from public.bot_events e
  where not exists (
    select 1 from public.bot_admins a where a.chat_id = e.chat_id
  );

grant select on public.bot_events_public to authenticated;

-- ─────────────────────────────────────────────────────────────────────────
-- سبدهای بازِ مشتری‌ها — «سبدِ رهاشده» در پنل.
--
-- `telegram_sessions.cart` وقتی سفارش ثبت شود خودِ ربات خالی‌اش می‌کند، پس هر
-- سبدِ **پر** یعنی کسی جنس برداشته و نرفته تا آخر. مبلغش همین‌جا حساب می‌شود تا
-- پنل مجبور نباشد کلِ سبدها را بکشد پایین و خودش جمع بزند.
-- مدیرها اینجا هم بیرون‌اند، به همان دلیلِ نمای بالا.
create or replace view public.bot_carts_open as
  select
    s.chat_id,
    s.customer_name,
    s.customer_phone,
    s.customer_city,
    jsonb_array_length(s.cart) as cart_items,
    s.updated_at,
    (select coalesce(sum(
        coalesce((i->>'quantity')::numeric, 0) * coalesce((i->>'unit_price')::numeric, 0)
      ), 0) from jsonb_array_elements(s.cart) i) as cart_total
  from public.telegram_sessions s
  where jsonb_typeof(s.cart) = 'array'
    and jsonb_array_length(s.cart) > 0
    and not exists (
      select 1 from public.bot_admins a where a.chat_id = s.chat_id
    );

grant select on public.bot_carts_open to authenticated;

-- ─────────────────────────────────────────────────────────────────────────
-- بستنِ دستِ کلیدِ عمومی روی این دو نما.
--
-- **این با اندازه‌گیری پیدا شد، نه با حدس.** بلافاصله بعد از ساختنِ نماها با
-- خودِ کلیدِ عمومیِ پنل رویشان `curl` زده شد: هر دو `200` می‌دادند — یعنی نامِ
-- مشتری، شماره‌ی تلفن و رفتارش با یک کلیدی که داخلِ جاواسکریپتِ پنل است
-- خواندنی بود.
--
-- علتش این است که نما با اختیارِ **مالکش** اجرا می‌شود و RLS را دور می‌زند، و
-- پیش‌فرضِ سوپابیس `select` را به `anon` هم داده بود. برای **جدول** این اتفاق
-- نمی‌افتد چون RLS پشتِ grant می‌ایستد؛ برای **نما** هیچ‌چیز پشتش نیست:
-- خودِ grant تنها کنترلِ دسترسی است (SEC-02).
--
-- بعد از این، همان `curl` روی هر دو `401 permission denied` گرفت. و برای اینکه
-- دوباره پیش نیاید، `server_audit.py` دسترسیِ همه‌ی نماها را با
-- `db_invariants.expected.json` مقابله می‌کند — نمای تازه‌ای که ثبت نشده باشد
-- دروازه را قرمز می‌کند.
revoke all on public.bot_events_public from anon, public;
revoke all on public.bot_carts_open  from anon, public;
grant select on public.bot_events_public to authenticated;
grant select on public.bot_carts_open  to authenticated;

-- ─────────────────────────────────────────────────────────────────────────
-- خطاهای گوشیِ مالک — «چشمِ ناظر» تا امروز کور بود.
--
-- پنل در `client_errors` می‌نوشت ولی **هیچ‌وقت نمی‌توانست بخواندش**: آن جدول
-- عمداً فقط سیاستِ insert دارد. یعنی هر خرابیِ خاموشی روی گوشیِ مالک ثبت می‌شد و
-- هیچ‌کس نمی‌دیدش — مگر اینکه کسی SQL Editorِ سوپابیس را باز کند، که در عمل
-- یعنی هیچ‌وقت.
--
-- نما به‌جای سیاستِ SELECT، تا آن تصمیمِ اولیه نشکند: خودِ جدول بسته می‌مانَد و
-- این فقط چیزی را می‌دهد که مالک می‌تواند رویش کاری بکند. `stack` و `ua`
-- عمداً نیستند — بلندترین فیلدها و محتمل‌ترین جا برای چیزی که بهتر است به
-- مرورگر نرود.
create or replace view public.client_errors_recent as
  select id, created_at, kind, screen, app_version, left(message, 300) as message
  from public.client_errors
  where created_at > now() - interval '30 days';

revoke all on public.client_errors_recent from anon, public;
grant select on public.client_errors_recent to authenticated;
