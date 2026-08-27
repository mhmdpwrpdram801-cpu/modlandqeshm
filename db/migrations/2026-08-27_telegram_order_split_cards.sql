-- پرداختِ تکه‌تکه: یک سفارش می‌تواند چند کارت داشته باشد (۱۴۰۵/۰۶/۰۵)
--
-- تا امروز `telegram_orders` فقط **یک** کارت داشت (`card_file_id` + `card_sent_at`)
-- و پیامِ مشتری همیشه می‌گفت «کلِ مبلغ رو به این کارت واریز کن». مالک گفت بعضی
-- مشتری‌ها نمی‌توانند کلِ پول را یک‌جا بزنند و باید بشود گفت «این‌قدر به این کارت،
-- بقیه به کارتِ دیگر».
--
-- `cards` یک آرایه‌ی jsonb است، به ترتیبِ فرستادن:
--   [{"fid":"<file_id عکسِ کارت>","amount":5000000,"at":"2026-08-27T…Z"}, …]
--
-- «مانده» از همین‌جا **حساب می‌شود**، ذخیره نمی‌شود:
--   مانده = total − مجموعِ amountها
-- عمدی است (ARCH-04): عددی که دو جا نگه داشته شود بالاخره یک روز دو مقدارِ
-- متفاوت می‌شود، و اینجا آن عدد **پول** است.
--
-- ⚠️ `card_file_id` و `card_sent_at` سرِ جا می‌مانند و معنی‌شان عوض نمی‌شود:
-- «اولین کارتی که رفت». پنل (`renderTgOrders`) و محافظِ ویرایشِ سفارش هر دو
-- روی `card_sent_at` تکیه دارند و این مهاجرت نباید زیرشان را خالی کند.
-- قرارِ ناگفته‌ای که ربات نگه می‌دارد: `cards` پر ⇔ `card_sent_at` پر.
--
-- ── چرا تریگر، نه فقط اعتبارسنجی در ربات ────────────────────────────────────
-- ربات تنها نویسنده‌ی این ستون است، ولی «تنها نویسنده‌ی امروز» با «تنها نویسنده‌ی
-- همیشه» یکی نیست. اگر مجموعِ کارت‌ها از جمعِ سفارش بیشتر شود، مشتری پیامی
-- می‌گیرد که از او **بیشتر از بدهی‌اش** پول می‌خواهد — و این خرابیِ خاموش است:
-- نه خطایی می‌دهد، نه در پنل دیده می‌شود. ARCH-02 می‌گوید تصمیمِ نهایی روی پول
-- سمتِ دیتابیس بنشیند، مثلِ `delete_invoice` که دو لایه دارد.
--
-- CHECK نمی‌شود نوشت چون به `jsonb_array_elements` و مجموع‌گیری نیاز دارد و
-- Postgres زیرپرس‌وجو را داخلِ CHECK نمی‌پذیرد. پس تریگرِ BEFORE.

alter table public.telegram_orders
  add column if not exists cards jsonb not null default '[]'::jsonb;

-- ── پرکردنِ گذشته ────────────────────────────────────────────────────────────
-- بر خلافِ مهاجرتِ ارسالی‌ها، اینجا پرکردن **لازم** است و حدس هم نیست: سفارشی که
-- `card_file_id` دارد یعنی همان یک کارت رفته و کلِ مبلغ به آن تخصیص داده شده.
-- بدونِ این، قرارِ «cards پر ⇔ card_sent_at پر» از همان روزِ اول برای سفارش‌های
-- قدیمی نقض می‌شود و مانده‌شان کلِ مبلغ حساب می‌شود — یعنی ربات دوباره از مشتری
-- پول می‌خواهد.
--
-- شرطِ `total > 0` لازم است چون تریگرِ پایین amountِ صفر را رد می‌کند. سفارشِ
-- صفرتومانی (تخفیفِ ۱۰۰٪) کارت هم لازم ندارد.
update public.telegram_orders
   set cards = jsonb_build_array(jsonb_build_object(
         'fid', card_file_id,
         'amount', total,
         'at', coalesce(card_sent_at, created_at)))
 where card_file_id is not null
   and coalesce(total, 0) > 0
   and cards = '[]'::jsonb;

create or replace function public.check_tg_order_cards()
returns trigger
language plpgsql
-- `security invoker` عمدی است و از `block_payment_on_cancelled_invoice` تقلید
-- می‌کند: این تابع هیچ جدولی نمی‌خواند و فقط NEW را می‌سنجد، پس اختیارِ مالک
-- لازم ندارد (SEC-10). `search_path` ثابت است تا هشدارِ بازرسِ سوپابیس نیاید.
set search_path = public
as $$
declare
  s numeric := 0;
  c jsonb;
  a numeric;
begin
  -- خالی بودن مثلِ آرایه‌ی خالی است، نه خطا: سفارشِ تازه هنوز کارتی ندارد.
  if new.cards is null then
    new.cards := '[]'::jsonb;
  end if;

  if jsonb_typeof(new.cards) <> 'array' then
    raise exception 'telegram_orders.cards باید آرایه باشد، نه %', jsonb_typeof(new.cards);
  end if;

  for c in select * from jsonb_array_elements(new.cards) loop
    if jsonb_typeof(c) <> 'object' then
      raise exception 'هر عضوِ cards باید شیء باشد';
    end if;
    if coalesce(c->>'fid', '') = '' then
      raise exception 'کارتِ بدونِ fid ثبت نمی‌شود';
    end if;
    -- عدد نبودنِ amount باید **خطا** بدهد نه صفر. صفر یک ادعاست، و ادعای غلط:
    -- سفارش «کامل تخصیص داده شده» به نظر می‌رسد در حالی که نشده.
    if jsonb_typeof(c->'amount') <> 'number' then
      raise exception 'amountِ کارت باید عدد باشد';
    end if;
    a := (c->>'amount')::numeric;
    if a <= 0 then
      raise exception 'amountِ کارت باید مثبت باشد، نه %', a;
    end if;
    s := s + a;
  end loop;

  if s > coalesce(new.total, 0) then
    raise exception 'مجموعِ کارت‌ها (%) از جمعِ سفارش (%) بیشتر است', s, coalesce(new.total, 0);
  end if;

  return new;
end;
$$;

drop trigger if exists trg_tg_order_cards_valid on public.telegram_orders;
create trigger trg_tg_order_cards_valid
  before insert or update on public.telegram_orders
  for each row execute function public.check_tg_order_cards();

-- ── راهِ برگشت ──────────────────────────────────────────────────────────────
-- drop trigger if exists trg_tg_order_cards_valid on public.telegram_orders;
-- drop function if exists public.check_tg_order_cards();
-- alter table public.telegram_orders drop column if exists cards;
-- و در bot/index.ts: cardsOf/assignedOf/remainOf، شاخه‌ی مبلغ در awaiting_card،
-- بازفرستادنِ کارت‌ها در paynow_، و callbackِ paytalk_.

-- ── چطور وارسی شد ───────────────────────────────────────────────────────────
-- روی دیتابیسِ واقعی، با همان الگوی تراکنشِ برگشت‌خورده که README برای هر
-- آزمایشِ پولی می‌گوید (یک بلوکِ DO که آخرش عمداً raise می‌کند). خروجی:
--
--   کارت‌دارهای قدیمی که پر شدند: 2 ▸ مبلغِ ناهماهنگ: 0 ▸ بی‌کارت ولی پر: 0
--   سفارشِ تازه cards دارد: []
--   تقسیمِ ۶م+۴م قبول شد، مجموع: 10000000
--   ✅ سرریز رد شد: مجموعِ کارت‌ها (11000000) از جمعِ سفارش (10000000) بیشتر است
--   ✅ مبلغِ صفر رد شد
--   ✅ مبلغِ رشته‌ای رد شد
--   ✅ شیء به‌جای آرایه رد شد
--   ✅ کارتِ بی‌fid رد شد
--
-- «مبلغِ رشته‌ای» مهم‌ترینشان است و عمداً با رقمِ فارسی («۵۰۰») سنجیده شد: اگر
-- تریگر نوع را نمی‌سنجید، `(c->>'amount')::numeric` روی آن رشته خطا می‌داد یا —
-- بدتر — روی رشته‌ی لاتین بی‌صدا قبول می‌شد و مبلغ از حساب می‌افتاد.
--
-- بعدش وارسی شد که چیزی جا نمانده باشد: سفارش ۴ · سفارشِ آزمایشیِ جامانده ۰ ·
-- کارت‌دار ۲ · تریگر ۱.
