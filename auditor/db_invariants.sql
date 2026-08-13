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
  (select json_agg(json_build_object('t',c.relname,'trg',t.tgname) order by c.relname)
     from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='public' and not t.tgisinternal) as triggers
