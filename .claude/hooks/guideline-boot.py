#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
هوکِ شروعِ نشست — این چیزی است که دستورالعمل را «خودکار» می‌کند.

در هر نشست اجرا می‌شود و یک بلوکِ کوتاه وارد متن می‌کند: نسخه‌ی فعالِ دستورالعمل،
دروازه‌ی وارسیِ پروژه، و اگر مهاجرتی معلق باشد، همان اول اعلامش می‌کند.
یعنی کاربر لازم نیست چیزی بنویسد یا یادش باشد که دستورالعملی هست.

قاعده‌ی سختِ این فایل: **هیچ‌وقت نشست را نمی‌شکند.** هر خطایی بیفتد، بی‌صدا
با کدِ ۰ بیرون می‌آید. هوکِ پرحرف یا خراب، بدتر از نبودنِ هوک است.
"""

from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
G = os.path.join(ROOT, "guidelines")

VERSION_RE = re.compile(r"^\*\*نسخه: `([^`]+)`\*\*", re.M)
# «## 2026.08.1 → 2026.09.1» و همچنین «## → 2026.08.1»
MIG_RE = re.compile(r"^##\s*(?:(\d{4}\.\d{2}\.\d+)\s*)?→\s*(\d{4}\.\d{2}\.\d+)\s*$", re.M)
LEVEL_RE = re.compile(r"^\*\*سطح:\*\*\s*(\S+)", re.M)


def vkey(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def pending(text: str, frm: str, to: str) -> list[tuple[str, str]]:
    """مهاجرت‌هایی که مقصدشان بینِ نسخه‌ی مُهرخورده و نسخه‌ی فعلی است."""
    out = []
    blocks = list(MIG_RE.finditer(text))
    for i, m in enumerate(blocks):
        target = m.group(2)
        if not (vkey(frm) < vkey(target) <= vkey(to)):
            continue
        body = text[m.end(): blocks[i + 1].start() if i + 1 < len(blocks) else len(text)]
        lvl = LEVEL_RE.search(body)
        out.append((target, lvl.group(1) if lvl else "نامشخص"))
    return sorted(out, key=lambda t: vkey(t[0]))


def main() -> int:
    guide = read(os.path.join(G, "FULLSTACK.md"))
    if not guide:
        return 0                                   # دستورالعمل نصب نیست — ساکت بمان

    m = VERSION_RE.search(guide)
    gv = m.group(1) if m else "?"

    try:
        with open(os.path.join(G, "lock.json"), encoding="utf-8") as f:
            lock = json.load(f)
    except (OSError, ValueError):
        lock = {}

    lv = lock.get("guideline_version")
    verify = [v.get("cmd", "") for v in lock.get("verify", []) if v.get("cmd")]

    lines = [
        "<fullstack-guideline>",
        f"دستورالعملِ فول‌استک نصب است و **فعال**: نسخه‌ی {gv} — `guidelines/FULLSTACK.md`.",
        "این فایل را همین اول بخوان و روی همه‌ی درخواست‌های این نشست اعمالش کن.",
        "کاربر لازم نیست به آن اشاره کند (ACT-01). محتوایش را خلاصه نکن (ACT-02).",
        "ترتیبِ اولویت: حرفِ کاربر > قاعده‌های پروژه > استثناهای lock.json > دستورالعمل (§۱).",
    ]

    if verify:
        lines.append("دروازه‌ی وارسی پیش از هر تحویل (DOD-02):")
        lines += [f"  $ {c}" for c in verify]

    waivers = lock.get("waivers", [])
    if waivers:
        lines.append(
            "استثناهای ثبت‌شده — این‌ها تصمیمِ آگاهانه‌اند، «اصلاح»شان نکن (MIG-05): "
            + "، ".join(f"{w.get('id')} ({w.get('scope')})" for w in waivers)
        )

    if lv and lv != gv:
        mig = read(os.path.join(G, "MIGRATIONS.md")) or ""
        rows = pending(mig, lv, gv)
        lines += [
            "",
            f"⚠️ مهاجرتِ معلق: کد با نسخه‌ی {lv} مُهر خورده ولی دستورالعمل روی {gv} است.",
        ]
        if rows:
            lines.append(f"{len(rows)} مهاجرت در صف:")
            lines += [f"  · {t} — سطح: {lvl}" for t, lvl in rows]
        lines += [
            "همین اول به کاربر بگو و بپرس الان انجام بدهی یا نه — خودسرانه اجرا نکن (MIG-01).",
            "برای اجرا: /gl-migrate",
        ]

    lines.append("</fullstack-guideline>")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                              # noqa: BLE001 — هوک هیچ‌وقت نشست را نمی‌شکند
        sys.exit(0)
