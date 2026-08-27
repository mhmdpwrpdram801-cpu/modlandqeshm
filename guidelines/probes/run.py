#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تستِ **خودِ کاوشگرها** — همان الگوی auditor/tests/.

    python3 guidelines/probes/run.py

هر مورد دو نمونه دارد:

  `bad/`  — قاعده را نقض می‌کند. کاوشگر **باید** بگیردش (کدِ خروجی ۱).
  `good/` — سالم است. کاوشگر **نباید** قرمز بدهد (کدِ خروجی ۰).

نمونه‌ی `good` نصفِ ارزش است: بدونش معلوم نمی‌شود کاوشگر همان نقض را می‌گیرد یا
به همه‌چیز قرمز می‌دهد — و کاوشگری که الکی قرمز بدهد، بعد از چند بار خاموش
می‌شود (`CORE-04`).

فقط کدِ خروجی مقابله نمی‌شود؛ **شناسه‌ی قاعده** هم، وگرنه ممکن است `bad` به
دلیلِ کاملاً دیگری قرمز شده باشد و ما خیال کنیم کاوشگرِ موردِ نظر کار کرده — که
خودش یک سبزِ توخالیِ دیگر است (`CORE-12`).
"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROBES = os.path.join(os.path.dirname(HERE), "rule-probes.py")
FIX = os.path.join(HERE, "fixtures")

# قاعده‌ای که در خروجیِ نمونه‌ی bad باید **نقض** شده باشد
EXPECT = {
    "secret":    "SEC-01",
    "lockfile":  "STACK-04",
    "gitignore": "GIT-06",
    "verify":    "DOD-02",
}


# نمونه‌ی ناقضِ «رمز» در مخزن **نگه داشته نمی‌شود**.
#
# اولین باری که با یک توکنِ ساختگیِ `sbp_…` کامیت شد، گیت‌هاب push را رد کرد و
# آن را «توکنِ شخصیِ Supabase» خواند. تأییدِ خوبی برای الگوی ماست، ولی یعنی
# نمی‌شود نگهش داشت — پس اینجا ساخته و بعدش پاک می‌شود. مزیتِ جانبی‌اش این است
# که چیزی که کامیت نشده، هیچ‌وقت به رمزِ واقعی تبدیل نمی‌شود.
GENERATED = {("secret", "bad"): "app.js"}


def run(case: str, kind: str) -> tuple[int, str]:
    d = os.path.join(FIX, case, kind)
    made = None
    fname = GENERATED.get((case, kind))
    if fname:
        made = os.path.join(d, fname)
        # رشته در زمانِ اجرا به هم چسبانده می‌شود، تا **خودِ همین فایل** هم الگوی
        # کامل را نداشته باشد و اسکنرِ گیت‌هاب رویش گیر ندهد.
        open(made, "w", encoding="utf-8").write(
            'const KEY = "sbp' + "_" + "0" * 40 + '";\n')
    try:
        r = subprocess.run([sys.executable, PROBES, d], capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr
    finally:
        if made and os.path.exists(made):
            os.remove(made)


def main() -> int:
    if not os.path.isdir(FIX):
        print("❌ پوشه‌ی fixtures نیست — این تست چیزی برای سنجیدن ندارد (CORE-12)")
        return 1
    cases = sorted(d for d in os.listdir(FIX) if os.path.isdir(os.path.join(FIX, d)))
    if not cases:
        print("❌ هیچ نمونه‌ای پیدا نشد (CORE-12)")
        return 1

    print("═" * 58)
    print(f"  تستِ کاوشگرها — {len(cases)} مورد، هرکدام دو نمونه")
    print("═" * 58)

    fails: list[str] = []
    for c in cases:
        rule = EXPECT.get(c, "")
        code, out = run(c, "bad")
        if code == 0:
            fails.append(f"{c}/bad: نقضِ کاشته‌شده **گرفته نشد** (کدِ خروجی ۰)")
            print(f"  ❌ {c}/bad  — نگرفت")
        elif rule and f"❌ {rule}" not in out:
            fails.append(f"{c}/bad: قرمز شد ولی نه به‌خاطرِ {rule} — شاید کاوشگرِ دیگری افتاده")
            print(f"  ❌ {c}/bad  — قرمزِ بی‌ربط")
        else:
            print(f"  ✅ {c}/bad  — گرفت ({rule})")

        code, out = run(c, "good")
        if code != 0:
            bad_lines = [l.strip() for l in out.splitlines() if l.strip().startswith("•")]
            fails.append(f"{c}/good: روی نمونه‌ی سالم قرمز داد — هشدارِ نادرست (CORE-04): "
                         + " | ".join(bad_lines[:2]))
            print(f"  ❌ {c}/good — هشدارِ نادرست")
        else:
            print(f"  ✅ {c}/good — ساکت ماند")

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
