#!/usr/bin/env python3
"""بازرسِ سمتِ سرور — رباتِ تلگرام و ثابت‌های دیتابیس.

پنل و ابزارِ خرج هرکدام دروازه دارند؛ **سمتِ سرور هیچ‌وقت نداشت**. و همان‌جاست که
پول ساخته می‌شود، غریبه‌ها ورودی می‌فرستند، و کلیدِ سرویس دستِ کد است.

    python3 auditor/server_audit.py                       # عکسِ کامیت‌شده را می‌سنجد
    python3 auditor/server_audit.py --db /tmp/db.json     # یا یک عکسِ دیگر
    python3 auditor/server_audit.py --max-age-days 60     # کهنه بودنِ عکس را هم خطا بگیر

بخشِ دیتابیس روی auditor/db_invariants.snapshot.json اجرا می‌شود که در مخزن است،
پس دیگر به یادِ کسی بند نیست. **ولی عکس، دیتابیسِ زنده نیست:** اگر کسی فردا یک قید
را از داشبورد بردارد، تا وقتی عکس تازه نشود اینجا سبز می‌مانَد. برای همین تاریخِ عکس
همیشه چاپ می‌شود و اجرای هفتگیِ gates.yml با --max-age-days کهنه بودنش را قرمز
می‌کند. تازه‌کردن: پرس‌وجوی auditor/db_invariants.sql را بزن (MCP یا psql) و خروجی
را با taken_at در snapshot.json بگذار.
"""
import argparse, hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOT_DEFAULT = os.path.join(ROOT, "bot/index.ts")
BOT = BOT_DEFAULT
BOT_README = os.path.join(ROOT, "bot/README.md")

PASS, FAIL, SKIP = [], [], []
def ok(m):   PASS.append(m); print("  ✅ " + m)
def bad(m):  FAIL.append(m); print("  ❌ " + m)
def skip(m): SKIP.append(m); print("  ⏭️  " + m)
def head(t): print("\n━━━ " + t + " ━━━")


def strip_comments(ts):
    out, i, n = [], 0, len(ts)
    while i < n:
        c = ts[i]
        if c in "\"'`":
            q = c; out.append(c); i += 1
            while i < n and ts[i] != q:
                out.append(ts[i]); i += 2 if ts[i] == "\\" else 1
            out.append(q); i += 1
        elif ts.startswith("//", i):
            j = ts.find("\n", i); i = n if j < 0 else j
        elif ts.startswith("/*", i):
            j = ts.find("*/", i + 2); i = n if j < 0 else j + 2
        else:
            out.append(c); i += 1
    return "".join(out)


def bot_checks(src, code):
    head("۱) رمز و کلید")
    # SEC-01: هیچ رمزی در مخزن. رشته‌ی بلندِ شبیهِ توکن یا کلید.
    leaks = []
    for m in re.finditer(r"['\"]([A-Za-z0-9_\-]{32,})['\"]", code):
        s = m.group(1)
        if re.fullmatch(r"[0-9a-f]{32,}", s) or ":" in s or s.count("_") == 0:
            if not re.fullmatch(r"[A-Za-z_]+", s):
                leaks.append(s[:12] + "…")
    ok("هیچ رشته‌ی شبیهِ رمز در کد نیست") if not leaks else bad("رشته‌ی مشکوک: " + "، ".join(leaks[:3]))

    for name in ("BOT_TOKEN", "SUPABASE_SERVICE_ROLE_KEY"):
        uses = re.findall(r"Deno\.env\.get\(['\"]" + name + r"['\"]\)", code)
        ok(f"{name} فقط از Deno.env خوانده می‌شود ({len(uses)} جا)") if uses \
            else bad(f"{name} از Deno.env خوانده نمی‌شود")

    head("۲) مجوز روی هر مسیر (SEC-03)")
    # هر مسیرِ عمومی باید یا احراز کند یا در فهرستِ آگاهانه‌ی زیر باشد با دلیل.
    # فهرست خالی است و باید خالی بمانَد. `?media=` تا نسخه‌ی ۳۸ اینجا بود چون
    # هدرِ Authorization نمی‌تواند بگیرد؛ حالا ژتونِ امضاشده در خودِ نشانی دارد و
    # مثلِ بقیه احراز می‌کند. **مسیرِ تازه را اینجا اضافه نکن مگر واقعاً چاره نباشد.**
    OPEN: dict[str, str] = {}
    # پنجره‌ی هر پارامتر تا شروعِ پارامترِ بعدی است، نه یک عددِ ثابت. با پنجره‌ی
    # بلند، بررسی محافظِ مسیرِ ?secret= را می‌دید و می‌گفت ?prime= هم احراز دارد —
    # یعنی دقیقاً همان سوراخی را که باید لو می‌داد، پنهان می‌کرد.
    marks = [(m.group(1), m.start()) for m in
             re.finditer(r"url\.searchParams\.get\(['\"](\w+)['\"]\)", code)]
    # «t» و «which» پارامترِ خودِ مسیرِ ویدیواند، نه مسیرِ جدا.
    marks = [(n, i) for n, i in marks if n not in ("which", "k", "t")]
    seen = []
    for idx, (p, start) in enumerate(marks):
        end = marks[idx + 1][1] if idx + 1 < len(marks) else len(code)
        seg = code[start:end]
        # «تابعِ احراز صدا زده شده» کافی نیست — با if(false) کد همچنان صدایش
        # می‌زند و هیچ‌کس را رد نمی‌کند. تستِ جهشی همین را لو داد (S2). پس سه چیز
        # با هم لازم است: مکانیزمِ احراز، یک خروجِ ۴۰۱/۴۰۳، و نبودِ شرطِ مرده.
        has_auth = bool(re.search(r"cronKey\(\)|Deno\.env\.get\(['\"]BOT_TOKEN|isAdmin\(|auth\.getUser\(|medCheck\(", seg))
        deny = re.search(r"status:\s*40[13]", seg)
        has_deny = bool(deny)
        # شرطِ مرده را فقط **دور و برِ خودِ محافظ** می‌گردیم. با گشتنِ کلِ بخش،
        # هر if(true) در نهصد خطِ بدنه‌ی وبهوک باعث می‌شد ?secret= «بی‌احراز»
        # گزارش شود — احرازی که کاملاً سرِ جایش است. پیامِ غلط از نبودِ پیام بدتر
        # است، چون آدم را دنبالِ سوراخی می‌فرستد که وجود ندارد (CORE-04).
        near = seg[max(0, deny.start() - 320):deny.end() + 80] if deny else ""
        dead = bool(re.search(r"if\s*\(\s*(false|true)\s*\)", near))
        guarded = has_auth and has_deny and not dead
        if guarded:
            ok(f"مسیرِ ?{p}= احراز دارد")
        elif p in OPEN:
            ok(f"مسیرِ ?{p}= عمداً باز است — {OPEN[p][:52]}…")
        else:
            seen.append(p)
    for p in seen:
        bad(f"مسیرِ ?{p}= بدونِ هیچ احراز هویتی کار می‌کند و در فهرستِ استثنا هم نیست")

    head("۳) دستورهای مدیر")
    # محافظ گاهی روی همان خط است و گاهی خطِ بعد؛ نگاهِ تک‌خطی /backup را
    # به‌غلط «بی‌محافظ» گزارش می‌کرد. سه خط بعدش هم دیده می‌شود.
    lines = src.splitlines()
    for cmd in ("/گزارش", "/backup", "/پخش", "/broadcast", "/report"):
        hit = [i for i, l in enumerate(lines) if cmd in l and "===" in l]
        if not hit:
            bad(f"دستورِ {cmd} در کد پیدا نشد")
            continue
        window = " ".join(lines[hit[0]:hit[0] + 4])
        (ok if "isAdmin" in window else bad)(
            f"دستورِ {cmd} پشتِ isAdmin است" if "isAdmin" in window
            else f"دستورِ {cmd} بدونِ isAdmin اجرا می‌شود")
    # قاعده‌ی مستندشده‌ی پروژه: این دستور عمداً حذف شده، برنگردد.
    (bad if "claimadmin" in code.lower() else ok)(
        "دستورِ claimadmin برگشته — هر غریبه‌ای می‌تواند مدیر شود"
        if "claimadmin" in code.lower() else "دستورِ claimadmin برنگشته است")

    head("۴) خطا و گزارش (OPS-03)")
    # مسیرِ cron نباید با شکستِ گزارش باز هم «ok» بدهد.
    cron = code[code.find("searchParams.get('cron')"):][:900]
    swallow = re.search(r"catch\s*\([^)]*\)\s*\{\s*console\.error\([^)]*\);?\s*\}", cron)
    if swallow and re.search(r"return new Response\('ok'\)", cron):
        bad("گزارشِ هفتگی اگر بیفتد، مسیرِ cron باز هم «ok» برمی‌گردانَد — شکست دیده نمی‌شود")
    else:
        ok("مسیرِ cron شکست را قورت نمی‌دهد")

    # catchِ خالیِ موجود عمدی است: کارهای فرعیِ «بهترین‌تلاش» مثلِ فرستادن به یکی از
    # چند مدیر یا پاک کردنِ پیامِ موقت. ممنوعیتِ مطلق فقط الکی قرمز می‌دهد و
    # MIG-04 هم می‌گوید کدِ کارکننده را به‌خاطرِ سلیقه دست نزن. پس سقف می‌گذاریم:
    # عدد فقط اجازه دارد پایین بیاید. یک catchِ خالیِ تازه یعنی یک خرابیِ خاموشِ تازه.
    BUDGET = 22
    empties = re.findall(r"catch\s*\([^)]*\)\s*\{\s*\}", code)
    n = len(empties)
    if n > BUDGET:
        bad(f"catchِ خالی از {BUDGET} به {n} رسید — خطای تازه‌ای بی‌صدا گم می‌شود")
    elif n < BUDGET:
        ok(f"catchِ خالی از {BUDGET} به {n} کم شد — سقف را در server_audit.py پایین بیاور")
    else:
        ok(f"catchِ خالی همان {BUDGET}ِ ثبت‌شده است (کارهای فرعیِ عمدی)")

    head("۵) شبکه‌ی خروجی (ARCH-06)")
    tg = code[code.find("async function tgCall"):][:700]
    (ok if re.search(r"AbortSignal|signal\s*:", tg) else bad)(
        "فراخوانیِ تلگرام مهلت دارد" if re.search(r"AbortSignal|signal\s*:", tg)
        else "tgCall مهلت (timeout) ندارد — یک درخواستِ آویزان تابع را نگه می‌دارد")

    head("۵.۵) نشانیِ امضاشده‌ی ویدیو (SEC-02، SEC-03)")
    # `?media=` نمی‌تواند هدرِ Authorization بگیرد چون پنل آن را در `<video src>`
    # می‌گذارد. پس امضا در خودِ نشانی می‌نشیند.
    #
    # سقفِ نرخِ درون‌حافظه‌ای اینجا **امتحان شد و کار نکرد**: اندازه‌گیری نشان داد هر
    # درخواست یک ایزوله‌ی تازه می‌گیرد، پس هیچ شمارنده‌ای بینِ درخواست‌ها نمی‌مانَد.
    # آن راه یک محافظِ قلابی بود و برداشته شد — دنبالش نرو.
    mm = re.search(r"url\.searchParams\.get\(['\"]media['\"]\)", code)
    nxt = re.search(r"url\.searchParams\.get\(['\"](?!media|which|k|t)\w+['\"]\)", code[mm.end():]) if mm else None
    mseg = code[mm.start(): mm.end() + (nxt.start() if nxt else len(code))] if mm else ""
    if not mm:
        bad("مسیرِ ?media= پیدا نشد — این بررسی جای درستی را نگاه نمی‌کند")
    elif not re.search(r"medCheck\(", mseg):
        bad("مسیرِ ?media= امضای نشانی را وارسی نمی‌کند (SEC-03)")
    elif not re.search(r"if \(!\w+ \|\| !\(await medCheck\(", mseg):
        bad("مسیرِ ?media= ژتونِ غلط را رد می‌کند ولی **نبودِ ژتون** را قبول می‌کند — "
            "این گامِ موقتِ DATA-02 بود و باید بسته می‌شد")
    elif not re.search(r"status:\s*401", mseg):
        bad("مسیرِ ?media= امضا را می‌سنجد ولی هیچ‌جا رد نمی‌کند")
    elif re.search(r"if\s*\(\s*(false|true)\s*\)", mseg):
        bad("وارسیِ امضای ?media= با یک شرطِ مرده خنثی شده")
    else:
        ok("مسیرِ ?media= امضای نشانی را وارسی می‌کند و با ۴۰۱ رد می‌کند")

    # امضا فقط وقتی ارزش دارد که کلیدش از خودِ BOT_TOKEN جدا باشد؛ وگرنه هر جای
    # دیگری که آن رمز را ببیند می‌تواند نشانیِ معتبر بسازد (جداسازیِ کلید).
    if re.search(r"crypto\.subtle\.digest\(['\"]SHA-256['\"]", code) and "media-url-v1" in code:
        ok("کلیدِ امضا از BOT_TOKEN مشتق می‌شود، خودش نیست")
    else:
        bad("کلیدِ امضای ویدیو از BOT_TOKEN جدا نشده")

    head("۵.۷) لاگ و سلامت (OPS-01، OPS-02، OPS-04)")
    # لاگِ متنیِ آزاد در سوپابیس قابلِ جست‌وجو نیست. هر خط باید JSON باشد و یک
    # شناسه‌ی همبستگی داشته باشد، وگرنه نمی‌شود پرسید «این درخواست چه بر سرش آمد؟».
    helper = re.search(r"function log\(rid[\s\S]{0,400}?\n\}", code)
    if not helper:
        bad("تابعِ لاگِ ساخت‌یافته وجود ندارد (OPS-01)")
    elif not ("JSON.stringify" in helper.group(0) and "rid" in helper.group(0)):
        bad("لاگ JSON نیست یا شناسه‌ی همبستگی ندارد (OPS-01)")
    else:
        ok("لاگ JSON است و شناسه‌ی همبستگی دارد")

    # console.error فقط حق دارد داخلِ همان تابع باشد. هر جای دیگری یعنی یک خطِ
    # آزاد که در جست‌وجو گم می‌شود.
    raw = [m.start() for m in re.finditer(r"console\.error\(", code)]
    inside = [i for i in raw if helper and helper.start() <= i <= helper.end()]
    (ok if len(raw) == len(inside) and raw else bad)(
        f"هر {len(raw)} console.error داخلِ خودِ تابعِ لاگ است"
        if len(raw) == len(inside) and raw
        else f"{len(raw) - len(inside)} console.errorِ آزاد مانده — لاگِ بی‌ساختار (OPS-01)")

    # سطح‌ها: سه‌تا کافی است و بیشتر از این فقط سردرگمی می‌سازد (OPS-02).
    lv = set(re.findall(r"log\(rid, '(\w+)'", code))
    (ok if lv and lv <= {"error", "warn", "info"} else bad)(
        f"سطح‌های لاگ همان سه‌تای مجازند: {sorted(lv)}" if lv and lv <= {"error", "warn", "info"}
        else f"سطحِ لاگِ ناشناخته: {sorted(lv - {'error', 'warn', 'info'})}")

    # OPS-04: مسیرِ سلامت باید **واقعاً وابستگی را بسنجد**، نه فقط ۲۰۰ بدهد.
    hm = re.search(r"url\.searchParams\.get\(['\"]health['\"]\)", code)
    hnx = re.search(r"url\.searchParams\.get\(['\"](?!health|which|k|t)\w+['\"]\)", code[hm.end():]) if hm else None
    hseg = code[hm.start(): hm.end() + (hnx.start() if hnx else len(code))] if hm else ""
    if not hm:
        bad("مسیرِ سلامت وجود ندارد (OPS-04)")
    elif "supabase.from" not in hseg:
        bad("مسیرِ سلامت به دیتابیس نمی‌زند — فقط می‌گوید «بالام» (OPS-04)")
    elif "503" not in hseg:
        bad("مسیرِ سلامت وقتی وابستگی نرسد هم ۲۰۰ می‌دهد — یعنی هیچ‌وقت قرمز نمی‌شود")
    else:
        ok("مسیرِ سلامت واقعاً دیتابیس را می‌سنجد و با ۵۰۳ رد می‌کند")

    # نسخه‌ی داخلِ کد باید با چیزی که README ثبت کرده یکی باشد، وگرنه بعد از
    # استقرار مستند بی‌صدا عقب می‌مانَد (OPS-06).
    mver = re.search(r"const BOT_VER = (\d+)", code)
    doc = re.search(r"نسخه‌ی مستقر: \*\*([۰-۹\d]+)\*\*", open(BOT_README, encoding="utf-8").read())
    fa = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    if not mver:
        bad("BOT_VER در کد نیست")
    elif not doc:
        bad("نسخه‌ی مستقر در bot/README.md ثبت نشده")
    elif mver.group(1) != doc.group(1).translate(fa):
        bad(f"BOT_VER={mver.group(1)} ولی README می‌گوید {doc.group(1)} — یکی‌شان عقب مانده")
    else:
        ok(f"BOT_VER با نسخه‌ی ثبت‌شده در README یکی است ({mver.group(1)})")

    head("۶) فرارِ خروجی (SEC-04)")
    (ok if re.search(r"function escH", code) else bad)(
        "تابعِ escH برای متنِ کاربر هست" if re.search(r"function escH", code)
        else "تابعِ فرارِ HTML وجود ندارد")

    head("۷) هم‌خوانیِ کپیِ مرجع (OPS-06)")
    # وقتی فایلِ دیگری سنجیده می‌شود (تستِ جهشی)، این بررسی بی‌معنی است: هر جهشی
    # هش را عوض می‌کند، پس همه‌ی جهش‌ها «گرفته» می‌شدند و نرخِ ۱۰۰٪ِ دروغ می‌ساخت.
    if os.path.abspath(BOT) != os.path.abspath(BOT_DEFAULT):
        skip("فایلِ غیرِمرجع سنجیده می‌شود — مقابله‌ی sha256 بی‌معنی است و رد شد")
        return
    real = hashlib.sha256(open(BOT, "rb").read()).hexdigest()
    doc = re.search(r"`([0-9a-f]{64})`", open(BOT_README, encoding="utf-8").read())
    if not doc:
        bad("sha256 در bot/README.md ثبت نشده")
    elif doc.group(1) != real:
        bad(f"sha256 نمی‌خواند: فایل {real[:12]}… ولی README {doc.group(1)[:12]}… — "
            "یعنی کد عوض شده و مستند به‌روز نشده")
    else:
        ok("sha256ِ فایل با چیزی که README ثبت کرده یکی است")


DB_WANT_KEYS = ("tables", "policies", "checks", "triggers")

def db_checks(path, max_age=None):
    head("۸) ثابت‌های دیتابیس")
    exp_path = os.path.join(HERE, "db_invariants.expected.json")
    if not path:
        skip("عکسِ دیتابیس داده نشده (--db) — این بخش سنجیده نشد، نه اینکه پاس شده باشد")
        return
    got = json.load(open(path, encoding="utf-8"))
    if isinstance(got, list):
        got = got[0]
    exp = json.load(open(exp_path, encoding="utf-8"))

    # **این بخش عکس را می‌سنجد، نه دیتابیسِ زنده را.** تفاوتش مهم است: اگر کسی
    # فردا یک قیدِ CHECK را از داشبورد بردارد، تا وقتی عکس تازه نشود اینجا سبز
    # می‌مانَد. پس تاریخِ عکس **همیشه** چاپ می‌شود تا کسی سبزِ اینجا را با
    # «دیتابیس سالم است» یکی نگیرد. تازه‌کردنش: پرس‌وجوی db_invariants.sql را
    # بزن و خروجی را در db_invariants.snapshot.json بگذار.
    taken = got.get("taken_at")
    if not taken:
        bad("عکسِ دیتابیس تاریخ ندارد — معلوم نیست مالِ کِی است")
    else:
        age = None
        try:
            from datetime import date
            y, m, d = (int(x) for x in taken.split("-"))
            age = (date.today() - date(y, m, d)).days
        except Exception:
            bad(f"تاریخِ عکس خوانده نشد: {taken}")
        if age is not None:
            if max_age is not None and age > max_age:
                bad(f"عکسِ دیتابیس {age} روزه است (سقف {max_age}) — این دروازه دیگر "
                    "چیزی را نمی‌سنجد؛ با db_invariants.sql تازه‌اش کن")
            else:
                ok(f"عکس مالِ {taken} است ({age} روز پیش) — سنجش روی همین عکس است، نه دیتابیسِ زنده")

    norm = lambda rows: sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in (rows or []))

    # RLS روی همه‌ی جدول‌ها — این یکی سخت‌گیرانه است، نه مقایسه‌ای:
    off = [t["t"] for t in (got.get("tables") or []) if not t.get("rls")]
    (ok if not off else bad)(
        f"هر {len(got.get('tables') or [])} جدولِ public سیاستِ سطرْمحور روشن دارد"
        if not off else "RLS خاموش روی: " + "، ".join(off))

    # جدول‌هایی که عمداً از راهِ API خوانده نمی‌شوند
    pols = got.get("policies") or []
    for t, why in (("app_config", "کلیدِ cron"), ("bot_admins", "فهرستِ مدیرها")):
        has = [p for p in pols if p["t"] == t]
        (ok if not has else bad)(
            f"{t} هیچ سیاستی ندارد — فقط با نقشِ سرویس خوانده می‌شود ({why})"
            if not has else f"{t} سیاست پیدا کرد: {[p['p'] for p in has]} — از API خواندنی شد")
    ce = [p for p in pols if p["t"] == "client_errors"]
    (ok if [p for p in ce if p["cmd"] == "INSERT"] and not [p for p in ce if p["cmd"] in ("SELECT", "ALL")]
        else bad)("client_errors فقط insert دارد و از API خوانده نمی‌شود"
                  if [p for p in ce if p["cmd"] == "INSERT"] and not [p for p in ce if p["cmd"] in ("SELECT", "ALL")]
                  else f"سیاستِ client_errors عوض شده: {[(p['p'], p['cmd']) for p in ce]}")

    # فاکتور فقط خواندنی است؛ نوشتنش از تابع‌های کنترل‌شده می‌گذرد
    for t in ("invoices", "invoice_items"):
        cmds = {p["cmd"] for p in pols if p["t"] == t}
        (ok if cmds == {"SELECT"} else bad)(
            f"{t} از API فقط خواندنی است" if cmds == {"SELECT"}
            else f"{t} حالا {cmds or 'هیچ سیاستی'} دارد — نوشتنِ مستقیم باز شد")

    # قیدها و تریگرها نباید بی‌صدا حذف شوند
    for key, label in (("checks", "قیدِ CHECK"), ("triggers", "تریگر")):
        a, b = norm(got.get(key)), norm(exp.get(key))
        missing = [json.loads(x) for x in b if x not in a]
        (ok if not missing else bad)(
            f"هر {len(b)} {label} سرِ جایش است"
            if not missing else f"{label}ِ گم‌شده: " +
            "، ".join(f"{m.get('t')}.{m.get('c') or m.get('trg')}" for m in missing[:4]))
    added = [json.loads(x) for x in norm(got.get("checks")) if x not in norm(exp.get("checks"))]
    if added:
        print(f"     (توجه: {len(added)} قیدِ تازه که در عکسِ ثبت‌شده نیست — اگر عمدی است عکس را به‌روز کن)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="خروجیِ JSONِ auditor/db_invariants.sql")
    ap.add_argument("--max-age-days", type=int, default=None,
                    help="اگر عکسِ دیتابیس از این کهنه‌تر بود، خطا بده (در اجرای زمان‌بندی‌شده)")
    ap.add_argument("--bot", default=None, help="فایلِ ربات (پیش‌فرض bot/index.ts) — برای تستِ جهشی")
    a = ap.parse_args()
    global BOT
    if a.bot: BOT = os.path.abspath(a.bot)
    # عکسِ کامیت‌شده پیش‌فرض است تا این هشت بررسی به یادِ کسی بند نباشد. قبلاً
    # بدونِ --db بی‌صدا رد می‌شدند، یعنی عملاً هیچ‌وقت اجرا نمی‌شدند.
    if not a.db:
        snap = os.path.join(HERE, "db_invariants.snapshot.json")
        if os.path.exists(snap): a.db = snap
    print("\n" + "═" * 52 + "\n  بازرسِ سمتِ سرور — ربات و دیتابیس\n" + "═" * 52)
    src = open(BOT, encoding="utf-8").read()
    bot_checks(src, strip_comments(src))
    db_checks(a.db, a.max_age_days)
    print("\n" + "═" * 52)
    print(f"  {len(PASS)} بررسی پاس شد")
    if SKIP: print(f"  ⏭️  {len(SKIP)} بخش سنجیده نشد")
    if FAIL:
        print(f"  ❌ {len(FAIL)} ایراد:")
        for f in FAIL: print("     • " + f)
    else:
        print("  ✅ بدونِ ایراد")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
