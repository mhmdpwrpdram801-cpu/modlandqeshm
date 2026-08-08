#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
جدولِ §۴ در FULLSTACK.md را از روی stack.json می‌سازد.

جدول دو جا نوشته نمی‌شود: stack.json منبعِ حقیقت است و این اسکریپت ناحیه‌ی بینِ
نشانه‌های STACK-TABLE را بازتولید می‌کند. بعد از هر check-drift.py --write
این را هم بزن، وگرنه self-check.py قرمز می‌شود — و درست هم می‌گوید.

  python3 guidelines/sync-table.py           # بنویس (همیشه ۰ اگر موفق باشد)
  python3 guidelines/sync-table.py --check   # فقط بسنج — ۱ یعنی عقب است (برای CI)

کدِ خروجی: 0 موفق · 1 فقط با --check و وقتی جدول عقب است · 2 خطا
تشخیصِ اینکه چیزی عوض شد یا نه با `git diff` است، نه با کدِ خروجی.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GUIDE = os.path.join(HERE, "FULLSTACK.md")
STACK = os.path.join(HERE, "stack.json")

BEGIN = "<!-- STACK-TABLE:BEGIN — ساختهٔ guidelines/sync-table.py — دستی ویرایش نکن -->"
END = "<!-- STACK-TABLE:END -->"
REGION = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)


def build(stack: dict) -> str:
    rows = [
        "| نقش | انتخاب | نسخه |",
        "|-----|--------|------|",
    ]
    for e in stack["entries"]:
        rows.append(f"| {e['role']} | {e.get('display', e['name'])} | {e['pinned']} |")

    return "\n".join([
        BEGIN,
        f"تاریخِ سنجشِ نسخه‌ها: **{stack['checked_at']}**",
        "",
        *rows,
        END,
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description="ساختِ جدولِ پشته از stack.json")
    ap.add_argument("--check", action="store_true", help="ننویس، فقط بسنج")
    args = ap.parse_args()

    try:
        with open(STACK, encoding="utf-8") as f:
            stack = json.load(f)
        with open(GUIDE, encoding="utf-8") as f:
            guide = f.read()
    except (OSError, ValueError) as exc:
        print(f"خواندن نشد: {exc}", file=sys.stderr)
        return 2

    if not REGION.search(guide):
        print(f"ناحیه‌ی جدول در {os.path.basename(GUIDE)} پیدا نشد — "
              f"نشانه‌های STACK-TABLE سرِ جایشان هستند؟", file=sys.stderr)
        return 2

    new = REGION.sub(lambda _: build(stack), guide, count=1)

    if new == guide:
        print("جدولِ §۴ به‌روز است.")
        return 0

    if args.check:
        print("جدولِ §۴ با stack.json نمی‌خواند — `python3 guidelines/sync-table.py` را بزن.",
              file=sys.stderr)
        return 1

    with open(GUIDE, "w", encoding="utf-8") as f:
        f.write(new)
    print(f"جدولِ §۴ از روی stack.json بازنویسی شد ({len(stack['entries'])} ردیف).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
