#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نصبِ بسته‌ی دستورالعمل روی یک پروژه‌ی تازه — بدونِ هیچ تنظیمِ دستی.

  cd /مسیرِ/پروژه
  curl -fsS https://raw.githubusercontent.com/mhmdpwrpdram801-cpu/modlandqeshm/main/guidelines/install.py | python3 -

یا اگر فایل را داری:  python3 install.py /مسیرِ/پروژه [--ref=شاخه]

چه می‌کند:
  ۱. کلِ بسته را از منبع می‌گیرد (سند + ابزار + هوک + دستورها)
  ۲. `lock.json` را برای همان پروژه می‌سازد — با دروازه‌ی وارسیِ کارکننده،
     نه کپیِ مُهرِ مخزنِ منبع
  ۳. `CLAUDE.md` را می‌سازد (یا اگر هست، فقط خطِ import را کنارش می‌گذارد)
  ۴. هوکِ SessionStart را در `.claude/settings.json` **ادغام** می‌کند
     (اگر از قبل تنظیماتی داشته باشد، خرابش نمی‌کند)
  ۵. گردش‌کارِ هفتگی را در `.github/workflows/` می‌گذارد
  ۶. کشِ محلی را به `.gitignore` اضافه می‌کند
  ۷. خودوارسی می‌گیرد و نتیجه را می‌گوید

هیچ‌جا لازم نیست چیزی را دستی عوض کنی: `is_origin` روی `auto` است و خودش از
روی remoteهای گیت می‌فهمد اینجا کپی است نه منبع.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

OWNER, REPO, DEFAULT_REF = "mhmdpwrpdram801-cpu", "modlandqeshm", "main"
TIMEOUT = 30
BASE = ""          # در main() از روی --ref پر می‌شود

# اگر منبع در دسترس نبود، از فهرستِ ثابت استفاده می‌شود؛ وگرنه از source.json.
FALLBACK = [
    "guidelines/FULLSTACK.md", "guidelines/MIGRATIONS.md", "guidelines/CHANGELOG.md",
    "guidelines/README.md", "guidelines/stack.json", "guidelines/source.json",
    "guidelines/check-drift.py", "guidelines/self-check.py", "guidelines/sync-table.py",
    "guidelines/gl-update.py", "guidelines/install.py",
    "guidelines/templates/guideline-upstream.yml",
    ".claude/hooks/guideline-boot.py",
    ".claude/commands/gl-check.md", ".claude/commands/gl-migrate.md",
    ".claude/commands/gl-sync.md", ".claude/commands/gl-pull.md",
]

HOOK_CMD = 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guideline-boot.py" 2>/dev/null || true'


def get(path: str) -> bytes:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "modland-guideline-install/1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def say(mark: str, msg: str) -> None:
    print(f"{mark} {msg}")


def file_list() -> list[str]:
    try:
        cfg = json.loads(get("guidelines/source.json").decode("utf-8"))
        paths = [e["path"] for e in cfg["files"]]
        for extra in ("guidelines/source.json", "guidelines/install.py"):
            if extra not in paths:
                paths.append(extra)
        return paths
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError, ValueError, KeyError):
        return FALLBACK


def detect_verify(root: str) -> list[dict]:
    """دروازه‌ی وارسی را از روی خودِ پروژه حدس بزن.

    `self-check.py` همیشه هست و همیشه کار می‌کند، پس نصبِ تازه از همان اول
    سبز است. اگر پروژه تستِ خودش را داشت، کنارش گذاشته می‌شود.
    """
    out = [{"name": "خودوارسیِ دستورالعمل",
            "cmd": "python3 guidelines/self-check.py",
            "note": "سازگاریِ درونیِ خودِ دستورالعمل. جای تستِ پروژه را نمی‌گیرد."}]

    pkg = os.path.join(root, "package.json")
    if os.path.isfile(pkg):
        try:
            with open(pkg, encoding="utf-8") as f:
                scripts = (json.load(f) or {}).get("scripts", {})
        except (OSError, ValueError):
            scripts = {}
        for name in ("test", "lint", "typecheck"):
            if name in scripts:
                out.append({"name": name, "cmd": f"npm run {name}", "note": "از package.json"})
    elif os.path.isfile(os.path.join(root, "pyproject.toml")):
        out.append({"name": "تستِ پایتون", "cmd": "python3 -m pytest -q",
                    "note": "اگر pytest ندارید، این خط را عوض کنید"})
    return out


def bundle_version(root: str) -> tuple[str | None, str | None]:
    """نسخه‌ای که دو فایلِ مستقلِ بسته ادعا می‌کنند."""
    import re as _re
    a = b = None
    try:
        with open(os.path.join(root, "guidelines", "FULLSTACK.md"), encoding="utf-8") as f:
            mm = _re.search(r"^\*\*نسخه: `([^`]+)`\*\*", f.read(), _re.M)
            a = mm.group(1) if mm else None
    except OSError:
        pass
    try:
        with open(os.path.join(root, "guidelines", "stack.json"), encoding="utf-8") as f:
            b = (json.load(f) or {}).get("guideline_version")
    except (OSError, ValueError):
        pass
    return a, b


IMPORT_BEGIN = "<!-- GUIDELINE-IMPORT:BEGIN — ساختهٔ guidelines/install.py -->"
IMPORT_END = "<!-- GUIDELINE-IMPORT:END -->"


def claude_md(root: str, verify: list[dict]) -> str:
    """`CLAUDE.md` را می‌سازد یا خطِ import را به فایلِ موجود اضافه می‌کند.

    هوکِ شروعِ نشست می‌گوید «این فایل را بخوان»، ولی `CLAUDE.md` خودِ دستورالعمل
    را در حافظه **بار می‌کند**. دو لایه بهتر از یکی است، و ترتیبِ اولویت هم
    همین‌جا نوشته می‌شود تا دستورالعملِ عمومی روی قاعده‌های پروژه سوار نشود.

    فایلِ موجود **هیچ‌وقت رونویسی نمی‌شود** — فقط یک بلوکِ نشانه‌دار به آن
    اضافه می‌شود، و اگر از قبل باشد دست نمی‌خورد.
    """
    path = os.path.join(root, "CLAUDE.md")
    gates = "\n".join(v["cmd"] for v in verify) or "python3 guidelines/self-check.py"

    block = f"""{IMPORT_BEGIN}
@guidelines/FULLSTACK.md

**ترتیبِ اولویت:** حرفِ صریحِ کاربر در همین گفت‌وگو › قاعده‌های مخصوصِ همین پروژه
(هرچه در همین فایل پایین‌تر بنویسی) › `guidelines/lock.json` → `waivers` ›
دستورالعملِ فول‌استک › پیش‌فرض‌های عمومی.

دستورالعمل **عمومی** است و این پروژه **خاص**. جایی که تناقض دیدی، قاعده‌ی پروژه برنده است.

**قبل از هر تحویل:**
```bash
{gates}
```

**دستورها:** `/gl-check` اختلافِ کد با دستورالعمل · `/gl-migrate` مهاجرت‌های معلق ·
`/gl-pull` گرفتنِ نسخه‌ی تازه از منبع
{IMPORT_END}"""

    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            body = f.read()
        if IMPORT_BEGIN in body or "guidelines/FULLSTACK.md" in body:
            return "از قبل بود — دست نخورد"
        with open(path, "a", encoding="utf-8") as f:
            if not body.endswith("\n"):
                f.write("\n")
            f.write("\n" + block + "\n")
        return "به فایلِ موجود اضافه شد (رونویسی نشد)"

    with open(path, "w", encoding="utf-8") as f:
        f.write("# راهنمای این پروژه برای Claude Code\n\n" + block + "\n")
    return "ساخته شد"


def merge_settings(root: str) -> str:
    """هوک را به `.claude/settings.json` اضافه کن بدونِ خراب کردنِ تنظیماتِ موجود."""
    path = os.path.join(root, ".claude", "settings.json")
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return "settings.json خوانده نشد — دستی هوک را اضافه کن"

    hooks = data.setdefault("hooks", {})
    starts = hooks.setdefault("SessionStart", [])
    for group in starts:
        for h in group.get("hooks", []):
            if "guideline-boot.py" in str(h.get("command", "")):
                return "از قبل بود"
    starts.append({"hooks": [{"type": "command", "command": HOOK_CMD}]})

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return "اضافه شد"


def main() -> int:
    global BASE
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ref = DEFAULT_REF
    for a in sys.argv[1:]:
        if a.startswith("--ref="):
            ref = a.split("=", 1)[1]
    BASE = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{ref}/"

    root = os.path.abspath(args[0] if args else os.getcwd())
    if not os.path.isdir(root):
        print(f"پوشه نیست: {root}", file=sys.stderr)
        return 2

    print(f"نصب روی: {root}  ·  از شاخه‌ی {ref}\n")

    # ۱) بسته — با وارسیِ یکدستی.
    #
    # raw.githubusercontent.com برای نامِ شاخه کشِ لبه دارد و **هر فایل جدا**
    # منقضی می‌شود. درست بعد از یک پوش، می‌شود نصفِ بسته را تازه گرفت و نصفش
    # را کهنه — بسته‌ی مخلوطی که نه کار می‌کند نه معلوم است چرا. پس بعد از هر
    # دور، دو فایلِ مستقل (FULLSTACK.md و stack.json) با هم مقابله می‌شوند و
    # اگر نخواندند، دوباره گرفته می‌شود.
    paths = file_list()
    got, failed = 0, []
    for attempt in range(1, 4):
        got, failed = 0, []
        for rel in paths:
            dest = os.path.join(root, rel)
            try:
                blob = get(rel)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
                failed.append(f"{rel} ({type(exc).__name__})")
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(blob)
            if rel.endswith(".py"):
                os.chmod(dest, 0o755)
            got += 1
        if not got:
            print("هیچ فایلی گرفته نشد — شبکه؟", file=sys.stderr)
            return 3

        va, vb = bundle_version(root)
        if va and vb and va == vb:
            break
        if attempt < 3:
            say("⏳", f"بسته یکدست نیست (FULLSTACK={va} · stack={vb}) — "
                     f"کشِ منبع هنوز نچرخیده. تلاشِ {attempt + 1} از ۳ بعد از ۳۰ ثانیه…")
            time.sleep(30)
    else:
        va, vb = bundle_version(root)
        print(f"\n❌ بسته یکدست نشد (FULLSTACK={va} · stack={vb}).", file=sys.stderr)
        print("   منبع همین چند دقیقه‌ی پیش به‌روز شده و کشِ raw هنوز نچرخیده.",
              file=sys.stderr)
        print("   چند دقیقه صبر کن و دوباره بزن — یا با SHAِ کامیت نصب کن که کش ندارد:",
              file=sys.stderr)
        print("   python3 install.py --ref=<SHA>", file=sys.stderr)
        return 3

    say("✅" if not failed else "⚠️", f"{got} فایل گرفته شد" +
        (f" · {len(failed)} نشد: {', '.join(failed)}" if failed else ""))

    # ۲) مُهرِ این پروژه، نه کپیِ مُهرِ منبع
    lock_path = os.path.join(root, "guidelines", "lock.json")
    version = "?"
    try:
        with open(os.path.join(root, "guidelines", "FULLSTACK.md"), encoding="utf-8") as f:
            import re
            mm = re.search(r"^\*\*نسخه: `([^`]+)`\*\*", f.read(), re.M)
            version = mm.group(1) if mm else "?"
    except OSError:
        pass

    if os.path.isfile(lock_path):
        say("·", "lock.json از قبل هست — دست نخورد")
    else:
        with open(lock_path, "w", encoding="utf-8") as f:
            json.dump({
                "schema": 1,
                "note": "مُهرِ انطباقِ این پروژه. هیچ‌وقت از منبع نمی‌آید (MIG-07).",
                "guideline_version": version,
                "applied_at": __import__("datetime").date.today().isoformat(),
                "verify": detect_verify(root),
                "areas": {},
                "waivers": [],
                "history": [{"version": version,
                             "date": __import__("datetime").date.today().isoformat(),
                             "note": "نصبِ اولیه با install.py"}],
            }, f, ensure_ascii=False, indent=2)
            f.write("\n")
        say("✅", f"lock.json ساخته شد (نسخه {version}) — دروازه‌ی وارسی خودکار پر شد")

    # ۳) CLAUDE.md — تا دستورالعمل واقعاً در حافظه بار شود، نه فقط هوک بگوید بخوانش
    try:
        with open(lock_path, encoding="utf-8") as f:
            gates = (json.load(f) or {}).get("verify", [])
    except (OSError, ValueError):
        gates = []
    say("✅", f"CLAUDE.md: {claude_md(root, gates)}")

    # ۴) هوک
    say("✅", f"هوکِ SessionStart: {merge_settings(root)}")

    # ۵) گردش‌کارِ هفتگی
    tpl = os.path.join(root, "guidelines", "templates", "guideline-upstream.yml")
    wf = os.path.join(root, ".github", "workflows", "guideline-upstream.yml")
    if os.path.isfile(tpl) and not os.path.isfile(wf):
        os.makedirs(os.path.dirname(wf), exist_ok=True)
        with open(tpl, encoding="utf-8") as s, open(wf, "w", encoding="utf-8") as d:
            d.write(s.read())
        say("✅", "گردش‌کارِ هفتگی در .github/workflows/ گذاشته شد")
    elif os.path.isfile(wf):
        say("·", "گردش‌کار از قبل هست")

    # ۶) gitignore
    gi = os.path.join(root, ".gitignore")
    line = "guidelines/.upstream-cache.json"
    body = ""
    if os.path.isfile(gi):
        with open(gi, encoding="utf-8") as f:
            body = f.read()
    if line not in body:
        with open(gi, "a", encoding="utf-8") as f:
            if body and not body.endswith("\n"):
                f.write("\n")
            f.write(line + "\n")
        say("✅", ".gitignore به‌روز شد")

    # ۷) وارسی
    print()
    rc = subprocess.run([sys.executable, os.path.join(root, "guidelines", "self-check.py")],
                        cwd=root).returncode
    print()
    if rc == 0:
        say("✅", "نصب تمام شد و خودوارسی سبز است.")
        print("   از این به بعد: هر نشست خودش نسخه را اعلام می‌کند و هفته‌ای یک بار")
        print("   اگر منبع جلو برود، در همین مخزن یک PR باز می‌شود.")
        print()
        print("   گامِ بعدی (اختیاری): در Claude Code بزن /gl-check تا ببینی کدِ فعلی")
        print("   کجاها با دستورالعمل نمی‌خواند، و بعد بخش‌ها را در lock.json مُهر بزن.")
    else:
        say("⚠️", "نصب انجام شد ولی خودوارسی قرمز است — خروجیِ بالا را ببین.")
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
