#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""دروازه‌های ثبت‌شده‌ی پروژه را اجرا کن — همان‌هایی که در lock.json → verify هستند.

    python3 guidelines/run-gates.py

چرا یک اجراکننده به‌جای نوشتنِ فرمان‌ها در گردش‌کار: فهرستِ دروازه‌ها با پروژه
عوض می‌شود، و هر جای دیگری که کپی‌اش کنیم بالاخره کهنه می‌شود. یک منبعِ حقیقت
(`lock.json`) و همه از همان می‌خوانند (`ARCH-04`).

**همه‌ی دروازه‌ها اجرا می‌شوند، حتی بعد از اولین قرمزی** — چون دیدنِ سه خرابی با
هم بهتر از سه بار رفت‌وبرگشت است. کدِ خروجی وقتی ۰ است که همه سبز باشند.

`CORE-12`: فهرستِ خالی هم خطاست، نه «چیزی برای اجرا نبود».
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOCK = os.path.join(HERE, "lock.json")


def main() -> int:
    if not os.path.isfile(LOCK):
        print("❌ guidelines/lock.json پیدا نشد — دروازه‌ای برای اجرا نیست.")
        return 1
    try:
        with open(LOCK, encoding="utf-8") as f:
            verify = (json.load(f) or {}).get("verify") or []
    except (OSError, ValueError) as e:
        print(f"❌ lock.json خوانده نشد: {e}")
        return 1

    if not verify:
        # CORE-12: «دروازه‌ای نبود» با «همه سبز» یکی نیست.
        print("❌ فهرستِ verify در lock.json خالی است — این پروژه دروازه ندارد.\n"
              "   اگر عمدی است، در waivers ثبتش کن؛ ولی سبز نمی‌دهیم.")
        return 1

    print("═" * 60)
    print(f"  دروازه‌های پروژه — {len(verify)} فرمان")
    print("═" * 60)

    failed: list[str] = []
    for i, e in enumerate(verify, 1):
        cmd = (e or {}).get("cmd", "").strip()
        name = (e or {}).get("name") or cmd
        if not cmd:
            print(f"\n[{i}/{len(verify)}] ❌ {name} — ورودیِ بدونِ فرمان")
            failed.append(name)
            continue
        print(f"\n[{i}/{len(verify)}] {name}\n  $ {cmd}")
        t0 = time.time()
        # shell لازم است چون فرمان‌ها می‌توانند `&&` و `cd` داشته باشند.
        r = subprocess.run(cmd, shell=True, cwd=ROOT)
        dt = time.time() - t0
        if r.returncode == 0:
            print(f"  ✅ سبز  ({dt:.1f}s)")
        else:
            print(f"  ❌ قرمز — کدِ خروجی {r.returncode}  ({dt:.1f}s)")
            failed.append(name)

    print("\n" + "═" * 60)
    if failed:
        print(f"  {len(verify) - len(failed)}/{len(verify)} سبز · {len(failed)} قرمز:")
        for f in failed:
            print("     • " + f)
        return 1
    print(f"  هر {len(verify)} دروازه سبز ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
