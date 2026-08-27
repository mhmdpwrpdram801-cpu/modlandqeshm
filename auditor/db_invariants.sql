-- ثابت‌های سمتِ دیتابیس. خروجی را به server_audit.py --db بده.
-- «باید» ها در auditor/db_invariants.expected.json ثبت شده‌اند؛ این پرس‌وجو فقط
-- واقعیتِ امروز را می‌گیرد. هیچ چیزی را عوض نمی‌کند — فقط خواندن.
select
  (select json_agg(json_build_object('t',c.relname,'rls',c.relrowsecurity) order by c.relname)
     from pg_class c join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='public' and c.relkind='r') as tables,
  (select json_agg(json_build_object('t',tablename,'p',policyname,'cmd',cmd) order by tablename,policyname)
     from pg_policies where schemaname='public') as policies,
  (select json_agg(json_build_object('t',rel.relname,'c',con.conname,'d',pg_get_constraintdef(con.oid)) order by rel.relname)
     from pg_constraint con join pg_class rel on rel.oid=con.conrelid
     join pg_namespace n on n.oid=rel.relnamespace
    where n.nspname='public' and con.contype='c') as checks,
  -- یکتایی‌ها جدا گرفته می‌شوند چون `checks` فقط contype='c' را می‌گیرد و قیدِ
  -- UNIQUE اصلاً در آن نمی‌افتاد. نبودنشان بی‌صداترین خرابیِ ممکن است:
  -- invoices_invoice_number_key تنها چیزی است که اگر منطقِ شماره‌دهی روزی از
  -- nextval به max+1 برگردد، جلوی **دو فاکتور با یک شماره** را می‌گیرد.
  (select json_agg(json_build_object('t',rel.relname,'c',con.conname,'d',pg_get_constraintdef(con.oid)) order by rel.relname,con.conname)
     from pg_constraint con join pg_class rel on rel.oid=con.conrelid
     join pg_namespace n on n.oid=rel.relnamespace
    where n.nspname='public' and con.contype in ('u','p')) as uniques,
  -- ترتیب‌شمارِ فاکتور نباید از خودِ داده عقب بیفتد. اگر بیفتد — بازگردانی از
  -- پشتیبان، یا یک setvalِ اشتباه — فاکتورِ بعدی به قیدِ یکتا می‌خورد و **ثبت
  -- نمی‌شود**. این عددِ لحظه‌ای است، پس فقط می‌گوید «سرِ عکس‌برداری عقب نبود».
  (select json_build_object(
            'seq_last', (select last_value from invoice_seq),
            'max_no',   coalesce((select max(invoice_number) from invoices), 0)
          )) as invoice_numbering,
  (select json_agg(json_build_object('t',c.relname,'trg',t.tgname) order by c.relname)
     from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='public' and not t.tgisinternal) as triggers,
  -- نماها **RLS را دور می‌زنند** (security_invoker خاموش)، پس برای یک نما خودِ
  -- grant همان کنترلِ دسترسی است — بر خلافِ جدول که RLS پشتِ grant می‌ایستد.
  -- کلیدِ anon داخلِ جاواسکریپتِ پنل است، یعنی عمومی (SEC-02). پس هر نمایی که
  -- anon رویش select داشته باشد، یعنی همان داده عمومی است.
  --
  -- `inv` = security_invoker. **این تعیین می‌کند که جمله‌ی بالا اصلاً صادق است یا
  -- نه**، و با اندازه‌گیری روشن شد: customer_balances به anon گرانتِ select دارد
  -- و با کلیدِ عمومی `200` می‌دهد، ولی `[]` برمی‌گردانَد در حالی که خودش ۲ ردیف
  -- دارد — چون security_invoker رویش **روشن** است و RLSِ جدول‌های زیرین پشتش
  -- می‌ایستد. آن دو نمای دیگر این را ندارند، برای همین باید `revoke` می‌شدند.
  -- پس «anon گرانت دارد» به‌تنهایی نه اثباتِ نشتی است نه اثباتِ امنیت؛ جفتش لازم است.
  (select json_agg(json_build_object(
            'v',c.relname,
            'anon',has_table_privilege('anon','public.'||c.relname,'select'),
            'auth',has_table_privilege('authenticated','public.'||c.relname,'select'),
            'inv', coalesce(array_to_string(c.reloptions,',') like '%security_invoker=true%', false)
          ) order by c.relname)
     from pg_class c join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='public' and c.relkind='v') as view_grants
