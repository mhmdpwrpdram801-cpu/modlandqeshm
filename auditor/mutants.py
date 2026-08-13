#!/usr/bin/env python3
"""کاشتنِ باگِ عمدی — چقدر از سوراخ‌های دروازه را می‌بینیم؟

«بازرس سبز است» یعنی هیچ‌کدام از چیزهایی که بلد بودیم بپرسیم خراب نیست. این
اسکریپت سؤالِ سخت‌تر را می‌پرسد: **اگر باگ باشد، می‌گیردش؟**

هر جهش یک باگِ واقعیِ ثبت‌شده در README را برمی‌گرداند. اگر بازرس روی جهش قرمز
شود، آن باگ پوشش دارد. اگر سبز بماند، همان‌جا یک سوراخِ نام‌دار پیدا کرده‌ایم.

    python3 auditor/mutants.py                # همه
    python3 auditor/mutants.py -k panel       # فقط پنل
    python3 auditor/mutants.py -k expenses -j 2

خروجی: نرخِ گرفتن + فهرستِ دقیقِ جهش‌هایی که از زیرِ دست در رفتند.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PANEL = "panel/index.html"
EXPENSES = "expenses/index.html"
CFG = {PANEL: "auditor/audit.config.json", EXPENSES: "expenses/audit.config.json"}

# ─────────────────────────────────────────────────────────────────────────────
# هر جهش: باگی که یک بار واقعاً به دستِ کاربر رسیده.
#   count = چند تطابق انتظار داریم. اگر نخواند، جهش اصلاً اجرا نمی‌شود —
#   درجِ کورکورانه همان چیزی است که یک بار باگِ </nav> را ساخت.
# ─────────────────────────────────────────────────────────────────────────────
MUTANTS = [
 # ── پنل ──────────────────────────────────────────────────────────────────
 dict(id="M01", file=PANEL, rule="UI-04", count=1,
      desc="متغیرِ رنگِ --danger در تمِ روشن تعریف‌نشده می‌ماند",
      find="--credit:#c0392b; --danger:#c0392b; --accent:#9a6f08; --profit:#1f7a44; --blue:#2563a8; --inv-hd-a:#f4ecd6; --inv-hd-b:#f8f2e4; --inv-gr-a:#f6efdc; --inv-gr-b:#fbf6ea; --rep-bg:#ffffff; --rep-ink:#221d15; --rep-line:#eeeeee; --rep-mut:#555555; --rep-dim:#999999; --ovbar:",
      repl="--credit:#c0392b; --accent:#9a6f08; --profit:#1f7a44; --blue:#2563a8; --inv-hd-a:#f4ecd6; --inv-hd-b:#f8f2e4; --inv-gr-a:#f6efdc; --inv-gr-b:#fbf6ea; --rep-bg:#ffffff; --rep-ink:#221d15; --rep-line:#eeeeee; --rep-mut:#555555; --rep-dim:#999999; --ovbar:"),

 dict(id="M02", file=PANEL, rule="UI-01/UI-03", count=1,
      desc="کنتراستِ کادرِ «این پیش‌فاکتور است» به gold-lt برمی‌گردد (۴٫۱۸)",
      find=".inv-note{margin-top:12px;text-align:center;color:var(--gold-dp)",
      repl=".inv-note{margin-top:12px;text-align:center;color:var(--gold-lt)"),

 dict(id="M03", file=PANEL, rule="UI-02/UI-10", count=1,
      desc="autofocusِ گزینه‌ی امن در پنجره‌ی پرسش برداشته می‌شود",
      find=" autofocus", repl=""),

 dict(id="M04", file=PANEL, rule="UI-05/DATA-04", count=1,
      desc="created_at خام چاپ می‌شود به‌جای jDate()",
      find="return { date:jDate(q.created_at), buyer_name:q.buyer",
      repl="return { date:String(q.created_at).slice(0,10), buyer_name:q.buyer"),

 dict(id="M05", file=PANEL, rule="UI-08", count=1,
      desc="نوارِ به‌روزرسانی دوباره z-index:9999 می‌گیرد",
      find="left:12px;right:12px;bottom:calc(var(--nav-h) + 10px);z-index:50;",
      repl="left:12px;right:12px;bottom:calc(var(--nav-h) + 10px);z-index:9999;"),
      # نکته: درجِ z-index:9999 در ابتدای همین قاعده هیچ اثری ندارد — اعلانِ
      # z-index:50 که بعدش می‌آید برنده می‌شود. جهشِ اول دقیقاً همین بود و دو بار
      # «سوراخ» گزارش شد تا معلوم شد اصلاً مقدار عوض نمی‌شده.

 dict(id="M06", file=PANEL, rule="SEC-04", count=1,
      desc="نامِ کالا بدونِ esc() داخلِ innerHTML می‌رود",
      find='openProductForm(\'${p.id}\')"><div><div class="li-main">${esc(p.name)}',
      repl='openProductForm(\'${p.id}\')"><div><div class="li-main">${p.name}'),

 dict(id="M07", file=PANEL, rule="UI-01", count=1,
      desc="viewport-fit=cover اضافه می‌شود (نوارِ پایین زیرِ نوارِ خانه‌ی آیفون)",
      find='content="width=device-width, initial-scale=1.0"',
      repl='content="width=device-width, initial-scale=1.0, viewport-fit=cover"'),

 dict(id="M08", file=PANEL, rule="API-04/ARCH-06", count=1,
      desc="تازه‌کردنِ توکن تک‌پروازه نیست (هفت درخواستِ هم‌زمان)",
      find="if(_refreshing) return _refreshing;", repl="if(false) return _refreshing;"),

 dict(id="M09", file=PANEL, rule="OPS-03", count=1,
      desc="پاسخِ کهنه‌ی جست‌وجو روی نتیجه‌ی تازه می‌نشیند (seqStale برداشته)",
      find="const invs=await sbGet(query);\n    if(seqStale('invList',_q))return;",
      repl="const invs=await sbGet(query);\n    if(false)return;"),

 dict(id="M10", file=PANEL, rule="UI-02", count=1,
      desc="controllerchange بدونِ شرطِ hadController — رفرشِ بی‌دلیلِ بارِ اول",
      find="if(!hadController)", repl="if(false)"),

 # ── ابزارِ خرج ────────────────────────────────────────────────────────────
 dict(id="M11", file=EXPENSES, rule="API-07/DATA-03", count=1,
      desc="مبلغِ فایلِ پشتیبان دوباره از پارسرِ انسانی رد می‌شود",
      find="var amount=amountOf(r.amount)", repl="var amount=parseNum(r.amount)"),

 dict(id="M12", file=EXPENSES, rule="SEC-04", count=1,
      desc="بابتِ خرج بدونِ esc() در لیست چاپ می‌شود",
      find="'<span class=\"rnote\">'+esc(r.note)+'</span>'",
      repl="'<span class=\"rnote\">'+r.note+'</span>'"),

 dict(id="M13", file=EXPENSES, rule="API-07", count=1,
      desc="محافظِ فرمولِ اکسل در CSV برداشته می‌شود",
      find="if(/^[=+\\-@\\t\\r]/.test(s)) s=\"'\"+s;", repl=""),

 dict(id="M14", file=EXPENSES, rule="DATA-04", count=1,
      desc="کبیسه‌ی اسفند غلط حساب می‌شود",
      find="function jLeap(jy){ return jalCal(jy).leap===0; }",
      repl="function jLeap(jy){ return jalCal(jy).leap===1; }"),

 dict(equiv="showModal خودش اولین عنصرِ فوکوس‌پذیر را فوکوس می‌کند و اینجا اولی همان «بی‌خیال» است — پس autofocus حشو است و برداشتنش رفتار را عوض نمی‌کند. (در پنل ترتیب برعکس است و آنجا واقعاً مهم است — M03.)", id="M15", file=EXPENSES, rule="UI-10/UI-02", count=1,
      desc="autofocusِ «بی‌خیال» برداشته می‌شود؛ Enter یعنی حذف",
      find=' autofocus', repl=''),

 dict(equiv="هر رشته‌ای که از ^\\d{1,15}$ رد شود عددِ صحیح است، پس parseInt و parseFloat یک جواب می‌دهند.", id="M16", file=EXPENSES, rule="DATA-03", count=1,
      desc="پول با اعشار خوانده می‌شود (parseFloat به‌جای عددِ صحیح)",
      find="return parseInt(s,10);\n}\nfunction esc(s){",
      repl="return parseFloat(s);\n}\nfunction esc(s){"),

 dict(equiv="اندازه‌گیری شد: ارتفاعِ طبیعیِ متنِ ۱۶ پیکسلی با padding از ۴۴ رد می‌شود، پس پایین آوردنِ min-height هیچ دکمه‌ای را کوچک نمی‌کند.", id="M17", file=EXPENSES, rule="UI-01", count=1,
      desc="هدفِ لمسیِ دکمه‌ها از ۴۴ به ۱۸ پیکسل می‌افتد",
      find=".btn{\n  min-height:44px; min-width:44px;",
      repl=".btn{\n  min-height:18px; min-width:18px;"),

 dict(id="M18", file=EXPENSES, rule="UI-01/UI-03", count=1,
      desc="رنگِ متنِ کم‌رنگ در تمِ تاریک کنتراست را می‌شکند",
      find="--ink2:#a9b3c1;", repl="--ink2:#3a424e;"),

 dict(id="M19", file=EXPENSES, rule="UI-11", count=1,
      desc="dir و lang از نشانه‌گذاری برداشته و به اسکریپت سپرده می‌شوند",
      find='<html lang="fa" dir="rtl" data-theme="light">',
      repl='<html data-theme="light">'),

 dict(equiv="load() همان پرچم را از راهِ probe می‌زند؛ این خط در آن مسیر اصلاً به کار نمی‌آید.", id="M20", file=EXPENSES, rule="OPS-03", count=1,
      desc="خطای نوشتن در حافظه بی‌صدا بلعیده می‌شود (هشدار نشان داده نمی‌شود)",
      find="if(!okw) MEM=true;", repl="if(!okw) MEM=false;"),
]


def run_audit(html_rel, engine, timeout):
    cfg = os.path.join(ROOT, CFG[html_rel])
    t0 = time.time()
    p = subprocess.run([sys.executable, os.path.join(ROOT, "auditor/audit.py"),
                        os.path.join(ROOT, html_rel), "-c", cfg, "-e", engine],
                       capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    out = p.stdout + p.stderr
    fails = re.findall(r"^     • (.+)$", out, re.M)
    return p.returncode, fails, round(time.time() - t0, 1), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", "--only", default="", help="فیلترِ زیررشته روی id، فایل یا شرح")
    ap.add_argument("-e", "--engine", default="chromium")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--baseline", action="store_true", help="فقط پایه را بگیر")
    a = ap.parse_args()

    sel = [m for m in MUTANTS if not a.only
           or a.only in m["id"] or a.only in m["file"] or a.only in m["desc"]]
    files = sorted({m["file"] for m in sel})

    print("═" * 60)
    print("  کاشتنِ باگِ عمدی — سنجشِ قدرتِ دروازه")
    print("═" * 60)

    # ۱) پایه: بدونِ جهش باید سبز باشد، وگرنه بقیه‌ی اعداد بی‌معنی‌اند (CORE-05)
    base = {}
    for f in files:
        rc, fails, secs, _ = run_audit(f, a.engine, a.timeout)
        base[f] = rc
        print(f"  پایه {f:24} → {'سبز ✅' if rc == 0 else '❌ قرمز ' + str(fails)}  ({secs}s)")
        if rc != 0:
            print("  پایه قرمز است؛ تا درست نشود عددِ جهش‌ها معنی ندارد.")
            sys.exit(2)
    if a.baseline:
        return

    originals = {f: open(os.path.join(ROOT, f), encoding="utf-8").read() for f in files}
    results = []
    try:
        for i, m in enumerate(sel, 1):
            src = originals[m["file"]]
            n = src.count(m["find"])
            path = os.path.join(ROOT, m["file"])
            if n != m["count"]:
                results.append(dict(m, verdict="نخورد", detail=f"{n} تطابق به‌جای {m['count']}"))
                print(f"\n  [{i}/{len(sel)}] {m['id']} ⚠️  جهش اجرا نشد — {n} تطابق به‌جای {m['count']}")
                continue
            open(path, "w", encoding="utf-8").write(src.replace(m["find"], m["repl"]))
            try:
                rc, fails, secs, _ = run_audit(m["file"], a.engine, a.timeout)
            finally:
                open(path, "w", encoding="utf-8").write(src)
            caught = rc != 0
            results.append(dict(m, verdict="گرفت" if caught else "در رفت",
                                detail="؛ ".join(fails[:2]) if fails else ""))
            mark = "✅ گرفت" if caught else "❌ در رفت"
            if m.get("equiv") and caught:
                mark += "  ⚠️ هم‌ارز فرض شده بود ولی گرفته شد — فرض را بازبین کن"
            print(f"\n  [{i}/{len(sel)}] {m['id']} ({m['rule']}) {mark}  ({secs}s)")
            print(f"       {m['desc']}")
            if fails:
                for f in fails[:3]:
                    print(f"       ↳ {f[:96]}")
    finally:
        for f, src in originals.items():
            open(os.path.join(ROOT, f), "w", encoding="utf-8").write(src)

    ran = [r for r in results if r["verdict"] != "نخورد" and not r.get("equiv")]
    equivs = [r for r in results if r.get("equiv") and r["verdict"] != "نخورد"]
    caught = [r for r in ran if r["verdict"] == "گرفت"]
    missed = [r for r in ran if r["verdict"] == "در رفت"]
    skipped = [r for r in results if r["verdict"] == "نخورد"]

    print("\n" + "═" * 60)
    print(f"  نرخِ گرفتن: {len(caught)}/{len(ran)}")
    if equivs:
        print(f"\n  ({len(equivs)} جهشِ هم‌ارز از شمارش کنار گذاشته شد — رفتاری را عوض نمی‌کنند،")
        print("   پس نه قوّتِ دروازه را ثابت می‌کنند نه ضعفش را:)")
        for r in equivs:
            print(f"     · {r['id']}: {r['equiv'][:88]}")
    if missed:
        print(f"\n  ❌ {len(missed)} باگ از زیرِ دستِ بازرس در رفت — اینجا بررسی لازم است:")
        for r in missed:
            print(f"     • [{r['rule']}] {r['desc']}   ({r['file']})")
    if skipped:
        print(f"\n  ⚠️  {len(skipped)} جهش اصلاً اجرا نشد (کد عوض شده؟ الگو را به‌روز کن):")
        for r in skipped:
            print(f"     • {r['id']}: {r['detail']} — {r['desc']}")
    json.dump(results, open("/tmp/mutants-result.json", "w"), ensure_ascii=False, indent=1)
    print("\n  جزئیات: /tmp/mutants-result.json")
    sys.exit(1 if missed else 0)


if __name__ == "__main__":
    main()
