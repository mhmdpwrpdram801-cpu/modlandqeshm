#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تستِ **مسیرِ به‌روزرسانی** — سه محافظِ gl-update.py.

    python3 guidelines/update-test.py

`DATA-09` می‌گوید پشتیبان تا وقتی بازگردانی‌اش را امتحان نکرده‌ای وجود ندارد.
همین حرف درباره‌ی به‌روزرسانی هم درست است: `gl-update.py` سه محافظ **ادعا**
می‌کرد و هیچ‌کدام یک بار هم اجرا نشده بودند. تا امروز این مخزن تنها نسخه‌ی
موجود بود، پس هیچ‌وقت کسی مسیرِ «کپی از منبع می‌گیرد» را طی نکرده بود — یعنی
دقیقاً همان پشتیبانِ برنگردانده.

سه محافظ:

  ۱ `never_touch` — مُهر (`lock.json`) هیچ‌وقت از منبع نمی‌آید (MIG-07).
    بدونش به‌روزرسانی مُهر را جلو می‌برد و مهاجرت‌ها **بی‌صدا گم می‌شوند**.
  ۲ فایلی که محلی عوض شده بدونِ `--force` رونویسی نمی‌شود.
  ۳ کدِ اجرایی (`kind: tool`) بدونِ `--with-tools` نمی‌آید.

**روشِ کار:** خودِ `gl-update.py`ِ واقعی در یک مخزنِ ساختگی کپی و **اجرا**
می‌شود، نه بازنویسی‌اش. چون `HERE`/`ROOT`/`BASELINE` را از `__file__` می‌سازد،
همان کپی روی همان پوشه کار می‌کند و ما هیچ مسیری را دستکاری نمی‌کنیم. فقط
`fetch` جایش عوض می‌شود تا به‌جای شبکه از پوشه‌ی «منبعِ» محلی بخواند.

⚠️ **این تست منطق را می‌سنجد، نه شبکه را** (`TEST-10`). خطای HTTP، مهلت، و
ریدایرکتِ گیت‌هاب اینجا اجرا نمی‌شوند و ادعایی هم درباره‌شان نمی‌کنیم.

هر محافظ **شاهدِ مثبت** هم دارد (`TEST-12`): فقط نمی‌پرسیم «نوشته نشد؟» — چون
اگر ماشینِ به‌روزرسانی اصلاً کار نکرده باشد هم جوابش همین است. برای هرکدام
نشان داده می‌شود که با برداشتنِ شرط (`--force`، `--with-tools`) یا در همان
اجرا روی فایلِ دیگر، نوشتن **واقعاً** اتفاق می‌افتد.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REAL = os.path.join(HERE, "gl-update.py")

OLD_DOC = "**نسخه: `2026.01.1`**\nمتنِ کهنه.\n"
NEW_DOC = "**نسخه: `2099.12.9`**\nمتنِ تازه‌ی منبع.\n"

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def build(tmp: str, lock_in_files: bool = False) -> tuple[str, str]:
    """یک «منبع» و یک «کپیِ کهنه» می‌سازد و مسیرشان را برمی‌گرداند.

    `lock_in_files` منبعِ **بدقواره** می‌سازد: مُهر هم در `files` آمده. این
    حالت اتفاقی نیست — با یک ویرایشِ اشتباه در `source.json` پیش می‌آید، و
    تنها چیزی که آن‌وقت جلویش را می‌گیرد `never_touch` است.
    """
    origin = os.path.join(tmp, "origin")
    copy = os.path.join(tmp, "copy")

    files = [
        {"path": "guidelines/FULLSTACK.md", "kind": "doc"},
        {"path": "guidelines/README.md", "kind": "doc"},
        {"path": "guidelines/self-check.py", "kind": "tool"},
    ]
    if lock_in_files:
        files.append({"path": "guidelines/lock.json", "kind": "doc"})

    cfg = {
        "schema": 1,
        "is_origin": False,
        "origin": {"kind": "github-raw", "owner": "o", "repo": "r", "ref": "main"},
        "files": files,
        "never_touch": ["guidelines/lock.json"],
    }

    # ── منبع: همه‌چیز تازه است، **از جمله یک lock.json متفاوت** ───────────
    # آن lock.json عمداً اینجاست: بدونِ آن، «مُهر عوض نشد» چیزی ثابت نمی‌کند،
    # چون چیزی هم نبوده که بیاید (TEST-12).
    write(os.path.join(origin, "guidelines", "FULLSTACK.md"), NEW_DOC)
    write(os.path.join(origin, "guidelines", "README.md"), "README تازه\n")
    write(os.path.join(origin, "guidelines", "self-check.py"), "# ابزارِ تازه\n")
    write(os.path.join(origin, "guidelines", "lock.json"),
          json.dumps({"guideline_version": "2099.12.9"}, ensure_ascii=False))

    # ── کپی: کهنه است ────────────────────────────────────────────────────
    write(os.path.join(copy, "guidelines", "FULLSTACK.md"), OLD_DOC)
    write(os.path.join(copy, "guidelines", "README.md"), "README کهنه\n")
    write(os.path.join(copy, "guidelines", "self-check.py"), "# ابزارِ کهنه\n")
    write(os.path.join(copy, "guidelines", "lock.json"),
          json.dumps({"guideline_version": "2026.01.1"}, ensure_ascii=False))
    write(os.path.join(copy, "guidelines", "source.json"),
          json.dumps(cfg, ensure_ascii=False, indent=2))

    # `README.md` را «محلی دست‌کاری‌شده» علامت می‌زنیم: baseline هشِ نسخه‌ی
    # همگام‌شده را دارد و محتوای روی دیسک با آن نمی‌خواند.
    shutil.copy(REAL, os.path.join(copy, "guidelines", "gl-update.py"))
    return origin, copy


def load(copy: str, origin: str):
    """ماژولِ کپی‌شده را بار می‌کند و fetch را به پوشه‌ی محلی وصل می‌کند."""
    path = os.path.join(copy, "guidelines", "gl-update.py")
    spec = importlib.util.spec_from_file_location("gl_update_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    fetched: list[str] = []

    def local_fetch(url: str) -> bytes:
        rel = url[len("local://"):]
        fetched.append(rel)
        p = os.path.join(origin, rel)
        if not os.path.exists(p):
            raise FileNotFoundError(rel)
        with open(p, "rb") as f:
            return f.read()

    mod.fetch = local_fetch
    mod.base_url = lambda origin_cfg: "local://"
    mod._fetched = fetched
    return mod


def seed_baseline(mod, copy: str) -> None:
    """README را «دست‌کاری‌شده» می‌کند: baseline هشِ چیزِ دیگری را دارد."""
    with open(os.path.join(mod.HERE, ".upstream.json"), "w", encoding="utf-8") as f:
        json.dump({"guidelines/README.md": mod.sha("README همگام‌شده\n".encode())}, f,
                  ensure_ascii=False)


def read(copy: str, rel: str) -> str:
    with open(os.path.join(copy, rel), encoding="utf-8") as f:
        return f.read()


def scenario(with_tools: bool, force: bool,
             lock_in_files: bool = False) -> tuple[dict, list[str], str]:
    """یک اجرای کامل در مخزنِ ساختگی. وضعیتِ فایل‌ها را برمی‌گرداند."""
    tmp = tempfile.mkdtemp(prefix="gl-update-test-")
    try:
        origin, copy = build(tmp, lock_in_files=lock_in_files)
        mod = load(copy, origin)
        seed_baseline(mod, copy)
        cfg = mod.read_json(mod.SOURCE)
        rows = mod.plan(cfg, "local://")
        mod.apply(rows, with_tools=with_tools, force=force)
        state = {rel: read(copy, rel) for rel in (
            "guidelines/FULLSTACK.md", "guidelines/README.md",
            "guidelines/self-check.py", "guidelines/lock.json")}
        return state, list(mod._fetched), tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print("═" * 58)
    print("  تستِ مسیرِ به‌روزرسانی — سه محافظِ gl-update.py")
    print("═" * 58)

    if not os.path.exists(REAL):
        print("❌ guidelines/gl-update.py نیست — این تست چیزی برای سنجیدن ندارد (CORE-12)")
        return 1

    # ── اجرای ساده: نه --with-tools، نه --force ───────────────────────────
    plain, fetched, _ = scenario(with_tools=False, force=False)

    # شاهدِ مثبت برای هر سه: ماشین **واقعاً** کار کرده و یک سند را جلو برده.
    check(plain["guidelines/FULLSTACK.md"] == NEW_DOC,
          "شاهدِ مثبت: سندِ عقب‌مانده واقعاً به‌روز شد",
          "اگر این نشود، بقیه‌ی «عوض نشد»ها هیچ چیزی ثابت نمی‌کنند (TEST-12)")

    # ── محافظِ ۱: مُهر از منبع نمی‌آید (MIG-07) ────────────────────────────
    #
    # ⚠️ **دو مکانیزمِ جدا اینجا هست و اولش گمراهم کرد.** اول فقط همین حالتِ
    # عادی را سنجیدم و سبز شد؛ بعد `if rel in never: continue` را عمداً از
    # `plan()` برداشتم و تست **همچنان سبز ماند**. علتش این بود که در پیکربندیِ
    # سالم `lock.json` اصلاً در `files` نیست، پس آن شرط هیچ‌وقت به آن نمی‌رسد —
    # کدِ مرده بود و من داشتم چیزِ دیگری را به اسمِ آن تأیید می‌کردم.
    #
    # پس دو ادعای جدا، با دو شاهد:
    #   ۱ در پیکربندیِ سالم: مُهر در فهرست نیست، پس سراغش هم نمی‌رود.
    #   ۲ در پیکربندیِ بدقواره (مُهر **در** فهرست): `never_touch` جلویش را
    #     می‌گیرد. این تنها حالتی است که آن شرط واقعاً کار می‌کند.
    lock = json.loads(plain["guidelines/lock.json"])
    check(lock.get("guideline_version") == "2026.01.1",
          "پیکربندیِ سالم: مُهر دست‌نخورده ماند",
          f"دیده شد: {lock.get('guideline_version')} — یعنی مهاجرت‌ها بی‌صدا گم می‌شوند")
    check("guidelines/lock.json" not in fetched,
          "پیکربندیِ سالم: مُهر اصلاً دانلود هم نشد",
          "plan() رفت سراغش: " + " · ".join(fetched))

    hostile, h_fetched, _ = scenario(with_tools=True, force=True, lock_in_files=True)
    h_lock = json.loads(hostile["guidelines/lock.json"])
    check(h_lock.get("guideline_version") == "2026.01.1",
          "پیکربندیِ بدقواره (مُهر در فهرست): never_touch نگهش داشت — MIG-07",
          f"دیده شد: {h_lock.get('guideline_version')} — مُهر از منبع آمد و مهاجرت‌ها گم شدند")
    check(hostile["guidelines/FULLSTACK.md"] == NEW_DOC,
          "شاهدِ مثبت: در همان اجرای بدقواره، سند واقعاً به‌روز شد",
          "پس «مُهر عوض نشد»ِ بالا مالِ محافظ است، نه مالِ اینکه اجرا اصلاً کار نکرده")

    # ── محافظِ ۳: کدِ اجرایی بدونِ --with-tools نمی‌آید ────────────────────
    check(plain["guidelines/self-check.py"] == "# ابزارِ کهنه\n",
          "کدِ اجرایی بدونِ --with-tools نیامد",
          "ابزار بی‌اجازه رونویسی شد — کدی که آدم ندیده اجرا می‌شود")

    with_tools, _, _ = scenario(with_tools=True, force=False)
    check(with_tools["guidelines/self-check.py"] == "# ابزارِ تازه\n",
          "شاهدِ مثبت: با --with-tools ابزار واقعاً آمد",
          "پس «نیامد»ِ بالا مالِ محافظ است، نه مالِ خرابیِ ماشین")

    # ── محافظِ ۲: فایلِ دست‌کاری‌شده بدونِ --force رونویسی نمی‌شود ─────────
    check(plain["guidelines/README.md"] == "README کهنه\n",
          "فایلِ محلی دست‌کاری‌شده بدونِ --force دست‌نخورده ماند",
          "کارِ محلی بی‌صدا بلعیده شد")

    forced, _, _ = scenario(with_tools=False, force=True)
    check(forced["guidelines/README.md"] == "README تازه\n",
          "شاهدِ مثبت: با --force همان فایل واقعاً رونویسی شد",
          "پس «دست‌نخورده ماند»ِ بالا مالِ محافظ است، نه مالِ اینکه اصلاً چیزی نیامده")

    print()
    failed = [r for r in results if not r[0]]
    for ok, name, detail in results:
        print(("  ✅ " if ok else "  ❌ ") + name)
        if not ok and detail:
            print("       ↳ " + detail)

    print("\n" + "═" * 58)
    if failed:
        print(f"  {len(results) - len(failed)}/{len(results)} سبز · {len(failed)} محافظ کار نکرد")
        return 1
    print(f"  هر {len(results)} بررسی سبز ✅ — سه محافظ واقعاً اجرا شدند")
    return 0


if __name__ == "__main__":
    sys.exit(main())
