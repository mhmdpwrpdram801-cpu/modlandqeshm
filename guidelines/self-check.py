#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
خودوارسیِ دستورالعمل.

دستورالعملی که خودش با خودش نمی‌خواند، از هر قاعده‌ای که در آن نوشته شده بی‌اعتبارتر است.
این اسکریپت سازگاریِ درونیِ guidelines/ را می‌سنجد — بدونِ شبکه، بدونِ وابستگی.

  python3 guidelines/self-check.py
  python3 guidelines/self-check.py -v     # همه‌ی بررسی‌ها را نشان بده، نه فقط خطاها

کدِ خروجی: 0 سالم · 1 دستِ‌کم یک ایراد
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

GUIDE = os.path.join(HERE, "FULLSTACK.md")
STACK = os.path.join(HERE, "stack.json")
LOCK = os.path.join(HERE, "lock.json")
CHANGELOG = os.path.join(HERE, "CHANGELOG.md")
MIGRATIONS = os.path.join(HERE, "MIGRATIONS.md")

PREFIXES = ("ACT", "PREC", "CORE", "DOD", "STACK", "ARCH", "DATA", "API", "SEC",
            "UI", "TEST", "OPS", "GIT", "SELF", "MIG")
RULE_RE = re.compile(r"\*\*(" + "|".join(PREFIXES) + r")-(\d{2})\b")
VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d+$")

FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((ok, name, detail))
    return ok


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    ap = argparse.ArgumentParser(description="خودوارسیِ دستورالعملِ فول‌استک")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    # ── فایل‌ها هستند؟ ────────────────────────────────────────────────────
    missing = [p for p in (GUIDE, STACK, LOCK, CHANGELOG, MIGRATIONS) if not os.path.isfile(p)]
    if not check(not missing, "همه‌ی فایل‌های مجموعه هستند",
                 "نبود: " + ", ".join(os.path.basename(p) for p in missing) if missing else ""):
        report(args.verbose)
        return 1

    guide = read(GUIDE)
    stack = read_json(STACK)
    lock = read_json(LOCK)
    changelog = read(CHANGELOG)
    migrations = read(MIGRATIONS)

    # ── نسخه‌ها یکی هستند؟ ────────────────────────────────────────────────
    m = re.search(r"^\*\*نسخه: `([^`]+)`\*\*", guide, re.M)
    guide_v = m.group(1) if m else None
    check(guide_v is not None, "نسخه در سرصفحه‌ی FULLSTACK.md پیدا شد")

    check(bool(guide_v and VERSION_RE.match(guide_v)),
          "قالبِ نسخه YYYY.MM.N است", f"دیده شد: {guide_v}")

    versions = {
        "FULLSTACK.md": guide_v,
        "stack.json": stack.get("guideline_version"),
        "lock.json": lock.get("guideline_version"),
    }
    m2 = re.search(r"^<!--\s*$.*?^\s*version:\s*(\S+)\s*$", guide, re.M | re.S)
    if m2:
        versions["FULLSTACK.md (سرآیندِ HTML)"] = m2.group(1)
    distinct = set(v for v in versions.values() if v)
    check(len(distinct) == 1, "نسخه در همه‌ی فایل‌ها یکی است",
          " · ".join(f"{k}={v}" for k, v in versions.items()) if len(distinct) != 1 else "")

    # ── نسخه در CHANGELOG ثبت شده؟ (SELF-01) ─────────────────────────────
    check(bool(guide_v) and f"## {guide_v}" in changelog,
          "نسخه‌ی فعلی ورودیِ CHANGELOG دارد (SELF-01)",
          f"«## {guide_v}» در CHANGELOG.md نیست")

    check(bool(guide_v) and guide_v in migrations,
          "نسخه‌ی فعلی در MIGRATIONS.md آمده (SELF-02)",
          f"«{guide_v}» در MIGRATIONS.md نیست")

    # ── شناسه‌ی قاعده‌ها ──────────────────────────────────────────────────
    found: dict[str, list[int]] = {}
    for pref, num in RULE_RE.findall(guide):
        found.setdefault(pref, []).append(int(num))

    dupes = []
    for pref, nums in found.items():
        seen = set()
        for n in nums:
            if n in seen:
                dupes.append(f"{pref}-{n:02d}")
            seen.add(n)
    check(not dupes, "هیچ شناسه‌ی تکراری نیست (SELF-03)", "تکراری: " + ", ".join(dupes))

    gaps = []
    for pref, nums in found.items():
        s = sorted(set(nums))
        expected = list(range(1, len(s) + 1))
        if s != expected:
            gaps.append(f"{pref}: {s}")
    check(not gaps, "شماره‌ها از ۱ پیوسته‌اند", " · ".join(gaps))

    unknown = set(found) - set(PREFIXES)
    check(not unknown, "همه‌ی پیشوندها شناخته‌شده‌اند", ", ".join(sorted(unknown)))

    total = sum(len(set(v)) for v in found.values())

    # ── عددِ اعلام‌شده با واقعیت می‌خواند؟ ─────────────────────────────────
    m3 = re.search(r"\*\*جمع: ([۰-۹\d]+) قاعده", guide)
    claimed = int(m3.group(1).translate(FA_DIGITS)) if m3 else None
    check(claimed == total, "عددِ اعلام‌شده‌ی قاعده‌ها با شمارشِ واقعی می‌خواند",
          f"اعلام‌شده {claimed} · واقعی {total}")

    # ── هر بخشِ فهرست، شناسه‌ی واقعی دارد ─────────────────────────────────
    index = re.search(r"## ۱۵\. فهرستِ شناسه‌ها(.*?)\*\*جمع:", guide, re.S)
    if index:
        listed = set(re.findall(r"`(" + "|".join(PREFIXES) + r")-01\.\.", index.group(1)))
        check(listed == set(found), "فهرستِ §۱۵ با بخش‌های واقعی می‌خواند",
              f"در فهرست نیست: {sorted(set(found) - listed)} · اضافه: {sorted(listed - set(found))}")
    else:
        check(False, "فهرستِ شناسه‌ها (§۱۵) پیدا شد")

    # ── جدولِ پشته با stack.json می‌خواند؟ ────────────────────────────────
    pins = {e["id"]: e["pinned"] for e in stack.get("entries", [])}
    absent = [f"{i}={v}" for i, v in pins.items() if v not in guide]
    check(not absent, "هر نسخه‌ی stack.json در جدولِ §۴ آمده", "نیامده: " + " · ".join(absent))

    check(stack.get("checked_at", "") in guide,
          "تاریخِ سنجشِ نسخه‌ها در §۴ به‌روز است",
          f"stack.json checked_at={stack.get('checked_at')} ولی در FULLSTACK.md نیست")

    # ناحیه‌ی ساخته‌شده‌ی جدول واقعاً بازتولیدِ stack.json است؟
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("sync_table", os.path.join(HERE, "sync-table.py"))
        st = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(st)                       # type: ignore[union-attr]
        region = st.REGION.search(guide)
        check(bool(region) and region.group(0) == st.build(stack),
              "جدولِ §۴ دقیقاً بازتولیدِ stack.json است",
              "با `python3 guidelines/sync-table.py` بازش‌ساز")
    except Exception as exc:                              # noqa: BLE001
        check(False, "sync-table.py قابلِ اجراست", f"{type(exc).__name__}: {exc}")

    # ── lock.json سالم است؟ ──────────────────────────────────────────────
    verify = lock.get("verify", [])
    check(isinstance(verify, list) and len(verify) > 0 and all("cmd" in v for v in verify),
          "lock.json دستِ‌کم یک دروازه‌ی وارسی دارد (DOD-02)")

    areas = lock.get("areas", {})
    check(bool(areas), "lock.json بخش‌های مُهرخورده دارد")
    ahead = [f"{k}={v.get('version')}" for k, v in areas.items()
             if v.get("version") and guide_v and v["version"] > guide_v]
    check(not ahead, "هیچ بخشی نسخه‌ای جلوتر از خودِ دستورالعمل ندارد", " · ".join(ahead))

    # ── استثناها به قاعده‌ی واقعی اشاره می‌کنند؟ (MIG-05) ────────────────
    all_ids = {f"{p}-{n:02d}" for p, nums in found.items() for n in nums}
    bad_ref, no_reason = [], []
    for w in lock.get("waivers", []):
        for rid in w.get("rules", []):
            if rid not in all_ids:
                bad_ref.append(f"{w.get('id')}→{rid}")
        if not w.get("reason") or not w.get("date"):
            no_reason.append(str(w.get("id")))
    check(not bad_ref, "هر استثنا به قاعده‌ی موجود اشاره می‌کند", " · ".join(bad_ref))
    check(not no_reason, "هر استثنا دلیل و تاریخ دارد (MIG-05)", " · ".join(no_reason))

    ids = [w.get("id") for w in lock.get("waivers", [])]
    check(len(ids) == len(set(ids)), "شناسه‌ی استثناها یکتاست")

    # ── فرمانِ وارسی واقعاً وجود دارد؟ ────────────────────────────────────
    broken = []
    for v in verify:
        first = v["cmd"].split()
        for tok in first:
            if "/" in tok and not tok.startswith("-"):
                if not os.path.exists(os.path.join(ROOT, tok)):
                    broken.append(f"{v.get('name')}: {tok}")
                break
    check(not broken, "فایلِ هر فرمانِ وارسی روی دیسک هست", " · ".join(broken))

    report(args.verbose)
    return 0 if all(ok for ok, _, _ in results) else 1


def report(verbose: bool) -> None:
    failed = [r for r in results if not r[0]]
    for ok, name, detail in results:
        if verbose or not ok:
            mark = "✅" if ok else "❌"
            print(f"{mark} {name}" + (f"\n     {detail}" if detail and not ok else ""))
    print(f"\n{len(results) - len(failed)}/{len(results)} بررسی پاس شد.")
    if failed:
        print("دستورالعمل با خودش نمی‌خواند — قبل از تحویل درستش کن.")


if __name__ == "__main__":
    sys.exit(main())
