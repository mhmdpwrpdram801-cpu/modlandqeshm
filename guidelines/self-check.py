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
import glob
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
SOURCE = os.path.join(HERE, "source.json")

PREFIXES = ("ACT", "PREC", "CORE", "DOD", "STACK", "ARCH", "DATA", "API", "SEC",
            "UI", "TEST", "OPS", "GIT", "SELF", "MIG")
# فقط *تعریفِ* قاعده، نه هر جایی که شناسه bold شده باشد. تعریف‌ها همیشه سرِ خط
# می‌آیند (`> **X-01 —` یا `- [ ] **X-01**`). بدونِ این لنگر، یک ارجاعِ درون‌متنیِ
# bold به قاعده‌ای که قبلاً تعریف شده، «شناسه‌ی تکراری» گزارش می‌شد — هشدارِ نادرست.
RULE_RE = re.compile(r"^(?:>\s*|-\s*\[\s*\]\s*)\*\*(" + "|".join(PREFIXES) + r")-(\d{2})\b", re.M)
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


def vkey(v: str) -> tuple[int, ...]:
    """کلیدِ مقایسه‌ی نسخه — عددی، نه رشته‌ای.

    مقایسه‌ی رشته‌ای «2026.08.10» را کوچک‌تر از «2026.08.9» می‌بیند و
    «2026.10.1» را کوچک‌تر از «2026.9.1». هر دو غلط‌اند.
    """
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def load_hook():
    """پارسرِ مهاجرت را از خودِ هوک بردار — یک منبعِ حقیقت، و هوک هم آزموده می‌شود."""
    import importlib.util
    path = os.path.join(ROOT, ".claude", "hooks", "guideline-boot.py")
    spec = importlib.util.spec_from_file_location("guideline_boot", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                          # type: ignore[union-attr]
    return mod


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

    # جست‌وجوی رشته‌ایِ ساده اینجا سبزِ دروغ می‌داد: نسخه در «قالبِ نمونه» هم
    # هست. پس با همان پارسری سنجیده می‌شود که هوک استفاده می‌کند، روی متنی که
    # بلوک‌های کد از آن حذف شده‌اند.
    try:
        hook = load_hook()
        targets = {t for _, t in hook.MIG_RE.findall(hook.strip_fences(migrations))}
        check(bool(guide_v) and guide_v in targets,
              "نسخه‌ی فعلی ورودیِ واقعی در MIGRATIONS.md دارد (SELF-02)",
              f"«{guide_v}» هدرِ واقعی ندارد. ورودی‌های دیده‌شده: {sorted(targets) or 'هیچ'}")
        check(all(vkey(t) > (0,) for t in targets) and bool(targets),
              "هدرهای MIGRATIONS.md قابلِ پارس‌اند", f"دیده شد: {sorted(targets)}")
    except Exception as exc:                              # noqa: BLE001
        check(False, "هوکِ guideline-boot.py قابلِ بارگذاری است", f"{type(exc).__name__}: {exc}")

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
             if v.get("version") and guide_v and vkey(v["version"]) > vkey(guide_v)]
    check(not ahead, "هیچ بخشی نسخه‌ای جلوتر از خودِ دستورالعمل ندارد", " · ".join(ahead))

    lock_v = lock.get("guideline_version")
    check(not (lock_v and guide_v) or vkey(lock_v) <= vkey(guide_v),
          "مُهرِ lock.json جلوتر از خودِ دستورالعمل نیست",
          f"lock={lock_v} · دستورالعمل={guide_v}")

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
    # همه‌ی مسیرهای فرمان سنجیده می‌شوند، نه فقط اولی — فرمانی که فایلِ
    # پیکربندی‌اش جابه‌جا شده باشد هم باید همین‌جا لو برود.
    broken = []
    for v in verify:
        for tok in v["cmd"].split():
            if "/" in tok and not tok.startswith("-") and not os.path.exists(os.path.join(ROOT, tok)):
                broken.append(f"{v.get('name')}: {tok}")
    check(not broken, "فایلِ هر مسیری که در فرمان‌های وارسی آمده هست", " · ".join(broken))

    # ── عددِ قاعده‌ها در README هم همان است؟ ──────────────────────────────
    readme = read(os.path.join(HERE, "README.md")) if os.path.isfile(os.path.join(HERE, "README.md")) else ""
    if readme:
        nums = {int(n.translate(FA_DIGITS)) for n in re.findall(r"([۰-۹\d]+) قاعده", readme)}
        check(not nums or nums == {total},
              "عددِ قاعده‌ها در README.md با FULLSTACK.md می‌خواند",
              f"README: {sorted(nums)} · واقعی: {total}")

    # ── هر مسیری که در مستندات نام برده شده واقعاً هست؟ ──────────────────
    # یک بار §۱۴ به `guideline-boot.sh` ارجاع می‌داد در حالی که فایل `.py` بود.
    # ارجاعِ مرده در مستند، کاربر را دنبالِ فایلی می‌فرستد که وجود ندارد.
    docs = [GUIDE, MIGRATIONS, CHANGELOG,
            os.path.join(HERE, "README.md"), os.path.join(ROOT, "CLAUDE.md")]
    docs += glob.glob(os.path.join(ROOT, ".claude", "commands", "*.md"))
    search_dirs = ["", "guidelines/", "guidelines/templates/", ".claude/",
                   ".claude/hooks/", ".claude/commands/", ".github/workflows/"]
    # فایل‌هایی که هنگامِ اجرا ساخته می‌شوند و در مخزن نیستند. اگر این‌ها را هم
    # «ارجاعِ مرده» بشماریم، بررسی همیشه قرمز می‌ماند و بعد از چند بار نادیده
    # گرفته می‌شود — و آن‌وقت ارجاعِ مرده‌ی واقعی را هم کسی نمی‌بیند (CORE-04).
    runtime_made = {".upstream.json", ".upstream-cache.json"}
    dead = []
    for doc in docs:
        if not os.path.isfile(doc):
            continue
        for ref in set(re.findall(r"`([A-Za-z0-9_./-]+\.(?:py|sh|md|json|yml|yaml|toml))`", read(doc))):
            if os.path.basename(ref) in runtime_made:
                continue
            if not any(os.path.exists(os.path.join(ROOT, d, ref)) for d in search_dirs):
                dead.append(f"{os.path.relpath(doc, ROOT)} → {ref}")
    check(not dead, "هر مسیرِ فایلی که در مستندات آمده وجود دارد", " · ".join(sorted(dead)))

    # ── بسته‌ی منبع سالم است؟ ────────────────────────────────────────────
    src = read_json(SOURCE) if os.path.isfile(SOURCE) else None
    if src:
        missing_files = [e["path"] for e in src.get("files", [])
                         if not os.path.exists(os.path.join(ROOT, e["path"]))]
        check(not missing_files,
              "هر فایلی که در source.json فهرست شده وجود دارد",
              "نبود: " + " · ".join(missing_files))

        kinds = {e.get("kind") for e in src.get("files", [])}
        check(kinds <= {"doc", "tool"}, "نوعِ هر فایلِ بسته doc یا tool است",
              f"ناشناخته: {sorted(kinds - {'doc', 'tool'})}")

        # قلبِ MIG-07: مُهر هیچ‌وقت نباید از منبع بیاید.
        check("guidelines/lock.json" in src.get("never_touch", []),
              "lock.json در never_touch هست (MIG-07)",
              "بدونِ آن، به‌روزرسانی مُهر را هم رونویسی می‌کند و مهاجرت‌ها گم می‌شوند")

        bundled = {e["path"] for e in src.get("files", [])}
        overlap = bundled & set(src.get("never_touch", []))
        check(not overlap, "هیچ فایلی هم‌زمان در بسته و در never_touch نیست",
              " · ".join(sorted(overlap)))

        check(isinstance(src.get("is_origin"), bool),
              "is_origin مقدارِ بولی دارد", f"دیده شد: {src.get('is_origin')!r}")

    # ── تاریخِ سرآیندِ HTML با تاریخِ متنِ سرصفحه یکی است؟ ─────────────────
    mh = re.search(r"^\s*updated:\s*(\d{4}-\d{2}-\d{2})\s*$", guide, re.M)
    mp = re.search(r"آخرین به‌روزرسانی:.*?\((\d{4}-\d{2}-\d{2})\)", guide)
    check(bool(mh) and bool(mp) and mh.group(1) == mp.group(1),
          "تاریخِ سرآیندِ HTML با تاریخِ سرصفحه یکی است",
          f"سرآیند={mh.group(1) if mh else '؟'} · سرصفحه={mp.group(1) if mp else '؟'}")

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
