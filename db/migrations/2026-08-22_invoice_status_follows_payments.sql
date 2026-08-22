-- ۱۴۰۵/۰۵/۳۱ — نشانِ فاکتور دنبالِ پرداخت‌ها بیفتد
--
-- باگی که مالک گزارش کرد: فاکتور را نسیه ثبت کرد، بعد «💰 ثبت پرداخت» را زد.
-- در لیستِ مشتری‌ها «تسویه» شد ولی در لیستِ فاکتورها همچنان «نسیه» ماند.
--
-- علتش این بود که دو سازوکارِ جدا وجود داشت و با هم حرف نمی‌زدند:
--   • «ثبت پرداخت» یک ردیف در payments می‌سازد → customer_balances درست صفر می‌شود
--   • ولی invoices.status سرِ ساختِ فاکتور یک بار حساب شده بود و دیگر عوض نمی‌شد
-- هیچ‌کدام از دو عدد غلط نبودند؛ فقط هماهنگ نبودند.
--
-- و یک دامِ بدتر یک قدم آن‌طرف‌تر بود: اگر روی همان فاکتور «✅ تسویه شد» را هم
-- می‌زد، settle_invoice مقدارِ paid_amount را برابرِ کلِ مبلغ می‌گذاشت در حالی که
-- ردیفِ پرداخت هم سرِ جایش بود. چون فرمولِ ماندهٔ حساب این است:
--     مانده = مجموع(total_amount − paid_amount) − مجموع(payments.amount)
-- همان مبلغ دوبار کم می‌شد و مانده منفی درمی‌آمد — یعنی پنل می‌گفت فروشنده به
-- مشتری بدهکار است. با داده‌ی واقعی سنجیده شد: −۶٬۵۴۰٬۰۰۰.

-- ── ۱) نشانِ فاکتور را از روی واقعیت حساب کن ────────────────────────────────
-- عمداً فقط status عوض می‌شود و paid_amount دست نمی‌خورد: customer_balances
-- پرداخت‌ها را جداگانه کم می‌کند، پس نوشتن در paid_amount ماندهٔ حساب را
-- دوبار کم می‌کرد — همان باگی که در settle_invoice بود.
create or replace function public.sync_invoice_status(p_invoice_id uuid)
returns void
language plpgsql
security definer
set search_path to 'public', 'pg_temp'
as $function$
declare v_total numeric; v_paid numeric; v_status text; v_extra numeric; v_new text;
begin
  if p_invoice_id is null then return; end if;

  select total_amount, coalesce(paid_amount,0), coalesce(status,'')
    into v_total, v_paid, v_status
    from invoices where id = p_invoice_id for update;
  if not found then return; end if;

  -- فاکتورِ باطل‌شده هیچ‌وقت دست نمی‌خورد
  if v_status = 'cancelled' then return; end if;

  select coalesce(sum(amount),0) into v_extra
    from payments where invoice_id = p_invoice_id;

  if v_total <= 0 or (v_paid + v_extra) >= v_total then v_new := 'paid';
  elsif (v_paid + v_extra) > 0 then v_new := 'partial';
  else v_new := 'credit';
  end if;

  if v_new is distinct from v_status then
    update invoices set status = v_new where id = p_invoice_id;
  end if;
end
$function$;

-- ── ۲) هر تغییری در payments، نشانِ فاکتورِ مربوطه را تازه کند ───────────────
create or replace function public.payments_sync_invoice_status()
returns trigger
language plpgsql
security definer
set search_path to 'public', 'pg_temp'
as $function$
begin
  -- هم فاکتورِ قبلی و هم فاکتورِ تازه، چون invoice_id ممکن است عوض شده باشد
  if tg_op <> 'INSERT' then perform sync_invoice_status(old.invoice_id); end if;
  if tg_op <> 'DELETE' then perform sync_invoice_status(new.invoice_id); end if;
  if tg_op = 'DELETE' then return old; end if;
  return new;
end
$function$;

drop trigger if exists trg_payments_sync_invoice_status on public.payments;
create trigger trg_payments_sync_invoice_status
after insert or update or delete on public.payments
for each row execute function public.payments_sync_invoice_status();

-- ── ۳) «تسویه شد» دیگر پرداخت‌های ثبت‌شده را دوبار حساب نکند ────────────────
create or replace function public.settle_invoice(p_invoice_id uuid)
returns void
language plpgsql
security definer
set search_path to 'public', 'pg_temp'
as $function$
declare v_status text; v_total numeric; v_extra numeric;
begin
  select status, total_amount into v_status, v_total
    from invoices where id = p_invoice_id for update;
  if not found then
    raise exception 'فاکتور پیدا نشد';
  end if;
  if coalesce(v_status,'') = 'cancelled' then
    raise exception 'فاکتورِ باطل‌شده را نمی‌شود تسویه کرد';
  end if;

  select coalesce(sum(amount),0) into v_extra
    from payments where invoice_id = p_invoice_id;

  update invoices
     set paid_amount = greatest(0, coalesce(v_total,0) - v_extra),
         status = 'paid'
   where id = p_invoice_id;
end
$function$;

-- ── راهِ برگشت ──────────────────────────────────────────────────────────────
-- drop trigger if exists trg_payments_sync_invoice_status on public.payments;
-- drop function if exists public.payments_sync_invoice_status();
-- drop function if exists public.sync_invoice_status(uuid);
-- و settle_invoice به نسخه‌ی قبلی برگردد:
--   update invoices set paid_amount = total_amount, status = 'paid' where id = p_invoice_id;

-- ── چطور وارسی شد ───────────────────────────────────────────────────────────
-- در یک تراکنشِ برگشت‌خورده روی دیتابیسِ واقعی (هیچ ردیفی جا نماند، شماره‌ی
-- فاکتور هم نسوخت):
--   ۱) فاکتورِ نسیه‌ی ۶٬۵۴۰٬۰۰۰ ......... نشان=credit   مانده=۶٬۵۴۰٬۰۰۰
--   ۲) بعد از پرداختِ کامل ............... نشان=paid     مانده=۰
--   ۳) بعد از «تسویه شد» هم .............. نشان=paid     مانده=۰   (قبلاً منفی می‌شد)
--   ۴) پرداختِ جزئیِ ۳ از ۱۰ ............. نشان=partial
