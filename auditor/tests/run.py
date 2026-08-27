#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تستِ خودِ بازرس — چیزی که تا امروز نداشتیم.

    python3 auditor/tests/run.py            # همه
    python3 auditor/tests/run.py dup_id nan # فقط چند مورد

بازرس پنل و ابزارِ خرج را می‌سنجد، ولی **هیچ‌چیز خودِ بازرس را نمی‌سنجید**. یعنی
اگر یک بررسی بی‌صدا از کار می‌افتاد، همه‌چیز سبز می‌ماند و کسی نمی‌فهمید — همان
سبزِ توخالیِ `CORE-12`، این بار یک لایه بالاتر.

**الگو: هر بررسی دو نمونه دارد.**

  `bad/`  — عمداً همان باگ را دارد. بازرس **باید** بگیردش (کدِ خروجی ۱).
  `good/` — سالم است. بازرس **نباید** قرمز بدهد (کدِ خروجی ۰).

نمونه‌ی `good` نصفِ ارزشِ کار است: بدونِ آن معلوم نمی‌شود بررسی واقعاً همان باگ
را می‌گیرد یا فقط به همه‌چیز قرمز می‌دهد. یک بررسیِ همیشه‌قرمز هم بی‌فایده است
(`CORE-04`).

فقط کدِ خروجی سنجیده نمی‌شود؛ **متنِ ایراد** هم مقابله می‌شود، وگرنه ممکن است
`bad` به دلیلِ کاملاً دیگری قرمز شده باشد و ما خیال کنیم بررسیِ موردِ نظر کار
کرده — که خودش یک سبزِ توخالیِ دیگر است.

اولین باری که همین اجرا شد، یک هشدارِ نادرستِ واقعی در `audit.py` لو داد:
تابعی که بعد از `;` روی همان خط تعریف شده بود «تعریف‌نشده» شمرده می‌شد.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AUDITOR = os.path.dirname(HERE)
AUDIT = os.path.join(AUDITOR, "audit.py")
FIX = os.path.join(HERE, "fixtures")

# متنی که در ایرادِ نمونه‌ی bad باید دیده شود — تا مطمئن شویم **همان** بررسی
# قرمز داده، نه یک بررسیِ دیگر.
EXPECT = {
    "dead_fn": "وجود ندارد",
    "dup_id":  "شناسه‌ی تکراری",
    "inline":  "درون‌خطی",
    "nan":     "NaN",
    "zindex":  "z-index",
    "narrow":  "باریک",
    "dynid":   "عنصرِ گمشده",
    "deadbtn": "بی‌اثر",
    "htmltag": "تگِ بسته‌نشده",
    "noverlay": "پنجره‌ای پیدا نشد",
}


def run_audit(case: str, kind: str) -> tuple[int, str]:
    d = os.path.join(FIX, case, kind)
    cmd = [sys.executable, AUDIT, os.path.join(d, "index.html"),
           "-c", os.path.join(d, "audit.config.json")]
    env = dict(os.environ, AUDIT_SHOTS=os.path.join("/tmp", f"selftest_{case}_{kind}"))
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def main() -> int:
    if not os.path.isdir(FIX):
        print("❌ پوشه‌ی fixtures نیست — این تست چیزی برای سنجیدن ندارد (CORE-12)")
        return 1
    wanted = sys.argv[1:]
    cases = sorted(d for d in os.listdir(FIX) if os.path.isdir(os.path.join(FIX, d)))
    if wanted:
        cases = [c for c in cases if c in wanted]
        if not cases:
            print(f"❌ هیچ موردی با {wanted} نخواند")
            return 1
    if not cases:
        print("❌ هیچ نمونه‌ای پیدا نشد (CORE-12)")
        return 1

    print("═" * 58)
    print(f"  تستِ خودِ بازرس — {len(cases)} مورد، هرکدام دو نمونه")
    print("═" * 58)

    fails: list[str] = []
    for c in cases:
        t0 = time.time()

        code, out = run_audit(c, "bad")
        want = EXPECT.get(c, "")
        if code == 0:
            fails.append(f"{c}/bad: بازرس باگِ کاشته‌شده را **نگرفت** (کدِ خروجی ۰)")
            print(f"  ❌ {c}/bad  — نگرفت")
        elif want and want not in out:
            fails.append(f"{c}/bad: قرمز شد ولی نه به‌خاطرِ «{want}» — شاید بررسیِ دیگری افتاده")
            print(f"  ❌ {c}/bad  — قرمزِ بی‌ربط")
        else:
            print(f"  ✅ {c}/bad  — گرفت")

        code, out = run_audit(c, "good")
        if code != 0:
            bad_lines = [l.strip() for l in out.splitlines() if l.strip().startswith("•")]
            fails.append(f"{c}/good: روی نمونه‌ی سالم قرمز داد — "
                         f"هشدارِ نادرست (CORE-04): {' | '.join(bad_lines[:2])}")
            print(f"  ❌ {c}/good — هشدارِ نادرست")
        else:
            print(f"  ✅ {c}/good — ساکت ماند   ({time.time() - t0:.1f}s)")

    print("\n" + "═" * 58)
    if fails:
        print(f"  {len(cases) * 2 - len(fails)}/{len(cases) * 2} سبز · {len(fails)} ایراد:")
        for f in fails:
            print("     • " + f)
        return 1
    print(f"  هر {len(cases) * 2} نمونه درست رفتار کرد ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
