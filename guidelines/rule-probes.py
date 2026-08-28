#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""کاوشگرهای قاعده — قاعده‌هایی که به‌جای نثر، **اجرا می‌شوند**.

    python3 guidelines/rule-probes.py [مسیرِ مخزن]
    python3 guidelines/rule-probes.py --list

کدِ خروجی: ۰ یعنی هیچ قاعده‌ای نقض نشده · ۱ یعنی نقض شده یا سنجیده نشد.

## چرا این فایل هست

`self-check.py` سازگاریِ **درونیِ** دستورالعمل را می‌سنجد: شماره‌گذاری، تعداد،
ورودیِ CHANGELOG. هیچ‌وقت نمی‌پرسد «آیا قاعده‌ای رعایت شده؟». `/gl-check` هم یک
پرامپت است — تکرارپذیر نیست و در CI اجرا نمی‌شود.

یعنی تا امروز **۱۱۶ قاعده داشتیم و هیچ‌کدام به‌تنهایی نمی‌توانستند یک build را
قرمز کنند.** هر دروازه‌ای که در مخزنِ منبع هست مخصوصِ همین پروژه است. پروژه‌ی
تازه‌ای که بسته را نصب می‌کند، نثر می‌گیرد و یک دروازه‌ی جانشین که همیشه قرمز است.

این فایل آن شکاف را — برای چند قاعده — پر می‌کند.

## چه چیزی اینجا هست و چه چیزی عمداً نیست

معیارِ ورود سخت است، چون `CORE-04` می‌گوید ابزاری که هشدارِ نادرست بدهد بعد از
چند بار نادیده گرفته می‌شود:

  ۱ **ماشین بتواند قطعی تصمیم بگیرد** — نه «به‌نظر می‌رسد».
  ۲ **نرخِ هشدارِ نادرست تقریباً صفر باشد** روی کدِ سالمِ واقعی.
  ۳ **نمونه‌ی جفتی داشته باشد** — یکی که باید بگیرد، یکی که باید ساکت بماند.

**`OPS-03` (catchِ خالی) عمداً اینجا نیست.** روی همین مخزن اندازه گرفته شد:
**۸۹** مورد، و تقریباً همه‌شان عمدی‌اند (`try { await send(...) } catch (_) {}` —
خبر دادن به مدیر بهترین‌کوشش است). کاوشگری که هر ۸۹ تا را قرمز کند، همان روزِ
اول خاموش می‌شود. آن قاعده جایی زور دارد که آدم قضاوت کند، نه regex — و تظاهر
به سنجیدنش بدتر از نسنجیدنش است.

به همین دلیل `DATA-03` (پول عددِ صحیح) هم نیست: بدونِ فهمِ تایپ نمی‌شود گفت یک
`float` پول است یا وزن.

**دو موردِ دیگر که سنجیده شدند و رد شدند (۱۴۰۵/۰۶/۰۶).** این‌ها را می‌نویسم تا
شش ماهِ دیگر کسی دوباره همین راه را نرود:

  · **`STACK-05` — منعِ `any`.** روی همین مخزن شمرده شد: **۵۱ مورد**، تقریباً
    همه در `bot/index.ts` که یک تابعِ لبه‌ی Deno بدونِ `tsconfig` است و
    `payload: any` برای APIی تلگرام واقعاً معقول است. کاوشگری که ۵۱ تا را قرمز
    کند همان روز خاموش می‌شود. اگر روزی لازم شد، شکلِ درستش **سقفِ نزولی** است
    (مثلِ شمارنده‌ی `catch`ِ خالی در `server_audit.py`) نه صفرِ مطلق — و سقف
    حالتِ **پروژه** است، پس جایش `lock.json` است نه این فایلِ عمومی.
    ⚠️ نیمه‌ی دیگرِ همین قاعده (`@ts-ignore` ممنوع، `@ts-expect-error` مجاز)
    سیگنالِ تمیزی دارد — **دقیقاً ۱ مورد** در کلِ مخزن. اضافه نشد چون آن یک
    مورد در `bot/index.ts` است و اصلاحش استقرارِ دوباره‌ی ربات را لازم دارد؛
    تصمیمش با مالک است، نه چیزی که بی‌صدا در یک PRِ دستورالعمل قاطی شود.

  · **`DATA-08` — خواندنِ بی‌سقف.** شمرده شد: **۴۵** فراخوانیِ `.select(` در
    برابرِ **۱۰** مورد `limit`/`range`. ولی اکثریتِ آن ۴۵ تا تک‌ردیفی‌اند
    (`.eq('id', …).single()`) و اصلاً سقف نمی‌خواهند. جدا کردنشان فهمِ پرس‌وجو
    لازم دارد نه regex، و بدونِ آن کاوشگر ~۳۵ هشدارِ نادرست می‌دهد.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

FAILS: list[str] = []
PASSES: list[str] = []
SKIPS: list[str] = []


def ok(rule: str, msg: str) -> None:
    PASSES.append(rule); print(f"  ✅ {rule} — {msg}")


def bad(rule: str, msg: str) -> None:
    FAILS.append(rule); print(f"  ❌ {rule} — {msg}")


def skip(rule: str, msg: str) -> None:
    # «موضوعش اینجا نیست» با «سنجیدم و سالم بود» یکی نیست. رد شدن دیده می‌شود
    # ولی خطا نیست — چون نبودنِ package.json تخلف نیست (CORE-12 معکوس).
    SKIPS.append(rule); print(f"  ⚪ {rule} — {msg}")


SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
             "build", ".next", "target", "vendor", ".mypy_cache", ".pytest_cache"}
TEXT_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".html", ".json",
            ".md", ".yml", ".yaml", ".sh", ".sql", ".toml", ".env", ".txt", ".css"}


def walk(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                yield os.path.join(dirpath, fn)


# ───────────────────────────── SEC-01 / DOD-06: رمز در مخزن
#
# فقط الگوهایی که **شکلشان خودش گویاست** — پیشوندِ رسمیِ سرویس یا بلوکِ کلیدِ
# خصوصی. دنبالِ «رشته‌ی بلندِ تصادفی» نمی‌گردیم، چون هشِ فایل و شناسه‌ی UUID و
# مقدارِ base64 هم همان شکل‌اند و هشدارِ نادرست می‌سازند.
SECRET_PATTERNS = [
    (r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----", "کلیدِ خصوصی"),
    (r"\bsbp_[0-9a-f]{40}\b",              "توکنِ Supabase (sbp_)"),
    (r"\bsk_live_[0-9a-zA-Z]{16,}\b",      "کلیدِ زنده‌ی Stripe"),
    (r"\bghp_[0-9A-Za-z]{36}\b",           "توکنِ GitHub (ghp_)"),
    (r"\bgithub_pat_[0-9A-Za-z_]{60,}\b",  "توکنِ GitHub (fine-grained)"),
    (r"\bAKIA[0-9A-Z]{16}\b",              "کلیدِ AWS"),
    (r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b",  "توکنِ Slack"),
    (r"\bAIza[0-9A-Za-z_\-]{35}\b",        "کلیدِ Google API"),
]


# نمونه‌های خودِ کاوشگر رمزِ الکی دارند — باید داشته باشند، وگرنه نمی‌شد ثابت
# کرد کاوشگر کار می‌کند. این‌ها دادهٔ **خودِ ابزار**اند و هیچ مخزنی نباید مجبور
# باشد بداند و دستی معافشان کند. اولین اجرای واقعی همین‌جا قرمز داد (CORE-04).
OWN_FIXTURES = os.path.join("guidelines", "probes", "fixtures")


def probe_secrets(root: str, allow: set[str]) -> None:
    hits = []
    for path in walk(root):
        rel = os.path.relpath(path, root)
        if rel in allow or rel.startswith(OWN_FIXTURES + os.sep):
            continue
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for pat, what in SECRET_PATTERNS:
            m = re.search(pat, text)
            if m:
                line = text[:m.start()].count("\n") + 1
                hits.append(f"{rel}:{line} — {what}")
    if hits:
        bad("SEC-01", "رمز در مخزن: " + " · ".join(hits[:4]) +
            ("" if len(hits) <= 4 else f" (و {len(hits)-4} مورد دیگر)") +
            " — پاک کردنِ کامیت کافی نیست، همان لحظه باطلش کن")
    else:
        ok("SEC-01", "هیچ رشته‌ی رمزشکلی پیدا نشد")


# ───────────────────────────── STACK-04: lockfile کامیت می‌شود
MANIFESTS = {
    "package.json":     ["package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb"],
    "pyproject.toml":   ["uv.lock", "poetry.lock", "pdm.lock", "requirements.txt"],
    "Cargo.toml":       ["Cargo.lock"],
    "go.mod":           ["go.sum"],
    "Gemfile":          ["Gemfile.lock"],
}


def probe_lockfile(root: str) -> None:
    found_any = False
    missing = []
    for manifest, locks in MANIFESTS.items():
        if not os.path.exists(os.path.join(root, manifest)):
            continue
        found_any = True
        if not any(os.path.exists(os.path.join(root, l)) for l in locks):
            missing.append(f"{manifest} → هیچ‌کدام از {', '.join(locks)}")
    if not found_any:
        skip("STACK-04", "هیچ فایلِ وابستگی‌ای نیست — چیزی برای قفل کردن وجود ندارد")
    elif missing:
        bad("STACK-04", "lockfile نیست: " + " · ".join(missing) +
            " — بدونش نصبِ CI با نسخه‌ی دیگری بالا می‌آید")
    else:
        ok("STACK-04", "هر فایلِ وابستگی lockfile کنارش دارد")


# ───────────────────────────── GIT-06 / SEC-01: فایلِ محیط در gitignore
ENV_NAMES = (".env", ".env.local", ".env.production", ".env.development")


def probe_gitignore(root: str) -> None:
    gi_path = os.path.join(root, ".gitignore")
    present = [n for n in ENV_NAMES if os.path.exists(os.path.join(root, n))]
    if not os.path.exists(gi_path):
        if present:
            bad("GIT-06", "فایلِ محیط هست (" + "، ".join(present) + ") ولی .gitignore نیست")
        else:
            skip("GIT-06", ".gitignore نیست و فایلِ محیطی هم نیست")
        return
    gi = open(gi_path, encoding="utf-8", errors="ignore").read()
    # الگوهایی که `.env` را می‌گیرند
    covered = bool(re.search(r"^\s*\.env(\*|$|/)", gi, re.M)) or bool(re.search(r"^\s*\*\.env\s*$", gi, re.M))
    if covered:
        ok("GIT-06", ".env در .gitignore پوشش دارد")
    elif present:
        bad("GIT-06", "فایلِ محیط هست (" + "، ".join(present) + ") و .gitignore پوششش نمی‌دهد")
    else:
        bad("GIT-06", ".env در .gitignore نیست — اولین باری که ساخته شود کامیت می‌شود")


# ───────────────────────────── CORE-12 / DOD-02: دروازه‌ی پروژه واقعی است
#
# این یکی خودِ **قاعده‌ی قاعده‌ها** را می‌سنجد: بسته‌ای که نصب می‌شود ولی
# دروازه‌اش خالی است، نثر می‌دهد و هیچ. مخزنِ منبع خودش یک بار همین حالت را
# داشت — نصبِ تازه در هشت ثانیه سبز می‌داد بی‌آنکه چیزی سنجیده باشد.
def probe_verify(root: str) -> None:
    import json
    lock_path = os.path.join(root, "guidelines", "lock.json")
    if not os.path.exists(lock_path):
        skip("DOD-02", "guidelines/lock.json نیست — این مخزن دستورالعمل را نصب نکرده")
        return
    try:
        lock = json.load(open(lock_path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        bad("DOD-02", f"lock.json خوانده نشد: {e}")
        return
    verify = lock.get("verify") or []
    if not verify:
        bad("DOD-02", "lock.json → verify خالی است — پروژه دروازه‌ی وارسی ندارد، "
                      "پس «سبز» هیچ معنایی نمی‌دهد")
        return
    # هر فرمان باید به فایلی اشاره کند که واقعاً هست، وگرنه دروازه‌ای که
    # اجرا نمی‌شود روی کاغذ سبز است.
    ghosts = []
    for step in verify:
        cmd = step.get("cmd", "")
        for tok in re.findall(r"[\w./-]+\.(?:py|sh|ts|js)\b", cmd):
            if not os.path.exists(os.path.join(root, tok)):
                ghosts.append(f"{step.get('name', '?')} → {tok}")
    if ghosts:
        bad("DOD-02", "دروازه به فایلی اشاره می‌کند که نیست: " + " · ".join(ghosts[:3]))
    else:
        ok("DOD-02", f"دروازه‌ی وارسی {len(verify)} فرمان دارد و همه‌شان وجود دارند")


# ───────────────────────────── GIT-01: روی شاخه‌ی اصلی مستقیم کار نکن
MAIN_BRANCHES = {"main", "master", "trunk", "develop"}


def _git(root: str, *args: str) -> str | None:
    import subprocess
    try:
        r = subprocess.run(["git", "-C", root, *args],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def probe_branch(root: str) -> None:
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch is None:
        skip("GIT-01", "مخزنِ گیت نیست — شاخه‌ای در کار نیست")
        return
    # CI روی کامیتِ ادغام چک‌اوتِ detached می‌کند و اسمِ شاخه «HEAD» می‌شود.
    # آنجا این قاعده اصلاً موضوعیت ندارد؛ قرمز دادنش یعنی هر PR قرمز است.
    if branch == "HEAD":
        skip("GIT-01", "چک‌اوتِ detached (احتمالاً CI) — شاخه‌ی کاری معنی ندارد")
        return
    if branch not in MAIN_BRANCHES:
        ok("GIT-01", f"کار روی شاخه‌ی جدا انجام می‌شود ({branch})")
        return
    # روی شاخه‌ی اصلی **نشستن** تخلف نیست؛ **کار کردن** رویش هست. معیارِ
    # «کار» تغییرِ کامیت‌نشده است — نه اینکه کسی صرفاً main را چک‌اوت کرده.
    # بدونِ این تفکیک، هر کلونِ تازه‌ای همان اول قرمز می‌شد (CORE-04).
    dirty = _git(root, "status", "--porcelain")
    if dirty is None:
        bad("GIT-01", "وضعیتِ گیت خوانده نشد — این بررسی اجرا نشد، پس پاس هم نشده (CORE-12)")
    elif dirty:
        n = len(dirty.splitlines())
        bad("GIT-01", f"روی «{branch}» {n} تغییرِ کامیت‌نشده هست — "
                      "شاخه‌ی جدا بساز، وگرنه برگشت و بازبینی هر دو سخت می‌شوند")
    else:
        ok("GIT-01", f"روی «{branch}» هستی ولی چیزی تغییر نکرده")


PROBES = [
    ("SEC-01",   "رمز در مخزن نباشد"),
    ("STACK-04", "lockfile کنارِ فایلِ وابستگی باشد"),
    ("GIT-06",   ".env در gitignore باشد"),
    ("DOD-02",   "دروازه‌ی وارسیِ پروژه واقعی باشد"),
    ("GIT-01",   "روی شاخه‌ی اصلی مستقیم کار نشود"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".", help="مسیرِ مخزن")
    ap.add_argument("--allow", default=None,
                    help="فایلی با فهرستِ مسیرهایی که از بررسیِ رمز معاف‌اند (هر خط یکی)")
    ap.add_argument("--list", action="store_true", help="فقط فهرستِ کاوشگرها را چاپ کن")
    a = ap.parse_args()

    if a.list:
        for rule, what in PROBES:
            print(f"{rule}\t{what}")
        return 0

    root = os.path.abspath(a.root)
    allow: set[str] = set()
    allow_path = a.allow or os.path.join(root, "guidelines", "probes-allow.txt")
    if os.path.exists(allow_path):
        allow = {ln.strip() for ln in open(allow_path, encoding="utf-8")
                 if ln.strip() and not ln.startswith("#")}

    print("═" * 58)
    print(f"  کاوشگرهای قاعده — {os.path.basename(root) or root}")
    print("═" * 58 + "\n")

    probe_secrets(root, allow)
    probe_lockfile(root)
    probe_gitignore(root)
    probe_verify(root)
    probe_branch(root)

    print("\n" + "═" * 58)
    print(f"  {len(PASSES)} پاس · {len(SKIPS)} رد · {len(FAILS)} نقض")
    if FAILS:
        print("  ❌ قاعده نقض شده — تحویل نده:")
        for f in FAILS:
            print("     • " + f)
        return 1
    print("  ✅ هیچ قاعده‌ای نقض نشده")
    return 0


if __name__ == "__main__":
    sys.exit(main())
