-- ۱۴۰۵/۰۵/۳۱ — حذفِ کاملِ فاکتورِ باطل‌شده (خواستِ مالک)
--
-- چرا RPC و نه DELETE از API: جدولِ invoices از راهِ API فقط خواندنی است و
-- server_audit همین را می‌سنجد. این نباید عوض شود.
--
-- چرا فقط باطل‌شده: حذفِ فاکتورِ زنده یعنی گم‌شدنِ فروشِ ثبت‌شده. برای پاک‌کردن باید
-- اول عمداً باطلش کنی — که خودش تأییدِ جدا دارد. دو درِ پشتِ‌سرِ‌هم، نه یکی.
--
-- سه چیزی که اگر رعایت نشود داده خراب می‌شود (هر سه با پرس‌وجو از خودِ دیتابیس
-- پیدا شدند، نه از حافظه):
--   • payments با ON DELETE SET NULL بسته شده → با حذفِ فاکتور **پاک نمی‌شود**،
--     یتیم می‌مانَد و همچنان از ماندهٔ حسابِ مشتری کم می‌کند. صریح پاک می‌شود.
--   • telegram_orders با NO ACTION بسته شده → حذف را **با خطا می‌خواباند**.
--     اول جدا می‌شود؛ آن سفارش دوباره قابلِ تبدیل به فاکتور می‌شود.
--   • returns ستونِ invoice_id دارد ولی **کلیدِ خارجی ندارد**، پس دیتابیس جلویش را
--     نمی‌گیرد و بی‌صدا آویزان می‌مانَد. صریح پاک می‌شود.
--   • invoice_items با CASCADE خودش می‌رود.
create or replace function public.delete_invoice(p_invoice_id uuid)
returns jsonb
language plpgsql
security definer
set search_path to 'public', 'pg_temp'
as $function$
declare
  v_status text; v_no integer; v_total numeric;
  v_pay integer := 0; v_ret integer := 0; v_tg integer := 0; v_items integer := 0;
begin
  if auth.uid() is null then
    raise exception 'برای حذفِ فاکتور باید وارد شده باشید';
  end if;

  select status, invoice_number, total_amount
    into v_status, v_no, v_total
    from invoices where id = p_invoice_id for update;
  if not found then
    raise exception 'فاکتور پیدا نشد';
  end if;

  if coalesce(v_status,'') <> 'cancelled' then
    raise exception 'فقط فاکتورِ باطل‌شده را می‌شود حذف کرد. اول باطلش کن.';
  end if;

  select count(*) into v_items from invoice_items where invoice_id = p_invoice_id;

  delete from payments where invoice_id = p_invoice_id;
  get diagnostics v_pay = row_count;

  delete from returns where invoice_id = p_invoice_id;
  get diagnostics v_ret = row_count;

  update telegram_orders set invoice_id = null where invoice_id = p_invoice_id;
  get diagnostics v_tg = row_count;

  delete from invoices where id = p_invoice_id;   -- invoice_items با CASCADE می‌رود

  return jsonb_build_object(
    'invoice_number', v_no, 'total_amount', v_total,
    'items', v_items, 'payments', v_pay, 'returns', v_ret, 'telegram_orders', v_tg
  );
end
$function$;

revoke all on function public.delete_invoice(uuid) from public, anon;
grant execute on function public.delete_invoice(uuid) to authenticated;

-- ── راهِ برگشت ──────────────────────────────────────────────────────────────
-- drop function if exists public.delete_invoice(uuid);
-- و دکمه‌های «حذفِ کاملِ فاکتور» و «حذفِ باطل‌شده‌ها» از panel/index.html برداشته شوند.

-- ── چطور وارسی شد ───────────────────────────────────────────────────────────
-- در یک تراکنشِ برگشت‌خورده روی دیتابیسِ واقعی (هیچ ردیفی جا نماند، شماره‌ی فاکتور
-- هم نسوخت چون invoice_number دستی داده شد):
--   ۱) فاکتورِ زنده ......... رد شد ✅ با پیامِ «اول باطلش کن»
--   ۲) بعد از ابطال ........ مانده=۲٬۰۰۰٬۰۰۰ (پرداختِ آن فاکتور هنوز کم می‌کرد)
--   ۳) حذف ................. قلم=۱ · پرداخت=۱ · مرجوعی=۱ · سفارشِ تلگرام=۰
--   ۴) ردیفِ یتیم .......... هیچ‌کدام؛ همه صفر
--   ۵) مانده بعدِ حذف ...... ۵٬۰۰۰٬۰۰۰ — دقیقاً همان فاکتورِ زنده ✅
