#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سنجشِ فاصله‌ی دستورالعمل با دنیای واقعی.

نسخه‌های پین‌شده در guidelines/stack.json را با رجیستری‌های عمومی مقایسه می‌کند و
می‌گوید کدام‌ها عقب افتاده‌اند و کدام عقب‌افتادگی «پرشِ نسخه‌ی اصلی» است.

  python3 guidelines/check-drift.py            # گزارشِ خوانا
  python3 guidelines/check-drift.py --json     # خروجیِ ماشینی (برای CI)
  python3 guidelines/check-drift.py --write    # پین‌ها را به‌روز کن (فقط minor/patch مگر با --allow-major)

کدِ خروجی:
  0 = هیچ عقب‌افتادگی‌ای نیست
  1 = عقب‌افتادگیِ minor/patch هست (مکانیکی، بی‌خطر)
  2 = عقب‌افتادگیِ major هست (نیاز به ورودیِ مهاجرت دارد)
  3 = خطای شبکه/اجرا

هیچ وابستگیِ بیرونی ندارد — فقط کتابخانه‌ی استانداردِ پایتون ۳.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
STACK = os.path.join(HERE, "stack.json")
TIMEOUT = 25
UA = "modland-guideline-drift/1 (+https://github.com/mhmdpwrpdram801-cpu/modlandqeshm)"


# ── ابزارِ نسخه ───────────────────────────────────────────────────────────────

def parse_version(v: str) -> tuple[list[int], str]:
    """'1.2.3-beta.1' → ([1,2,3], 'beta.1'). بخشِ پیش‌انتشار جدا می‌شود."""
    v = str(v).strip().lstrip("v")
    pre = ""
    for sep in ("-", "+"):
        if sep in v:
            v, pre = v.split(sep, 1)
            break
    nums = []
    for part in v.split("."):
        m = re.match(r"^\d+", part)
        nums.append(int(m.group()) if m else 0)
    while len(nums) < 3:
        nums.append(0)
    return nums, pre


def is_prerelease(v: str) -> bool:
    return bool(parse_version(v)[1])


def newer(a: str, b: str) -> bool:
    """آیا a از b جدیدتر است؟

    وقتی اعداد یکی‌اند، نسخه‌ی نهایی از پیش‌انتشار جدیدتر است — وگرنه اگر کسی
    «5.0.0-rc.1» پین کرده باشد، انتشارِ «5.0.0» هیچ‌وقت گزارش نمی‌شد.
    """
    na, pa = parse_version(a)
    nb, pb = parse_version(b)
    if na != nb:
        return na > nb
    return not pa and bool(pb)


def bump_kind(old: str, new: str) -> str:
    o, n = parse_version(old)[0], parse_version(new)[0]
    if n[0] != o[0]:
        return "major"
    if n[1] != o[1]:
        return "minor"
    return "patch"


# ── رجیستری‌ها ───────────────────────────────────────────────────────────────

def http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def latest_npm(name: str) -> str:
    return http_json(f"https://registry.npmjs.org/{name}/latest")["version"]


def latest_pypi(name: str) -> str:
    return http_json(f"https://pypi.org/pypi/{name}/json")["info"]["version"]


def latest_node(_name: str) -> str:
    """جدیدترین نسخه‌ی LTSِ فعال — نه current. عمداً: قاعده‌ی runtime در stack.json."""
    data = http_json("https://nodejs.org/dist/index.json")
    for entry in data:                       # فهرست از جدید به قدیم مرتب است
        if entry.get("lts"):
            return entry["version"].lstrip("v")
    raise RuntimeError("هیچ نسخه‌ی LTS در فهرستِ node پیدا نشد")


def latest_eol(name: str) -> str:
    """جدیدترین چرخه‌ای که هنوز پشتیبانی می‌شود (endoflife.date).

    تاریخ از ساعتِ سیستم خوانده می‌شود، نه ثابت — یک تاریخِ ثابت در کد یعنی
    سالِ بعد نسخه‌های ازرده‌خارج‌شده «زنده» گزارش می‌شوند و کسی نمی‌فهمد.
    """
    today = datetime.date.today().isoformat()
    data = http_json(f"https://endoflife.date/api/{name}.json")
    for cycle in data:                       # از جدید به قدیم
        eol = cycle.get("eol")
        if eol is False or (isinstance(eol, str) and eol > today):
            return str(cycle["cycle"])
    raise RuntimeError(f"هیچ چرخه‌ی زنده‌ای برای {name} پیدا نشد")


FETCHERS = {"npm": latest_npm, "pypi": latest_pypi, "node": latest_node, "eol": latest_eol}


# ── منطقِ اصلی ───────────────────────────────────────────────────────────────

def check(stack: dict) -> tuple[list[dict], list[dict]]:
    """(نتیجه‌ها, خطاها) — هر خطای شبکه یک ورودی را می‌سوزاند نه کلِ اجرا را."""
    results, errors = [], []
    for e in stack["entries"]:
        reg = e["registry"]
        fetch = FETCHERS.get(reg)
        if fetch is None:
            errors.append({"id": e["id"], "error": f"رجیستریِ ناشناخته: {reg}"})
            continue
        try:
            latest = fetch(e["name"])
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
                KeyError, ValueError, RuntimeError) as exc:
            errors.append({"id": e["id"], "error": f"{type(exc).__name__}: {exc}"})
            continue

        # نسخه‌ی پیش‌انتشار هیچ‌وقت پیشنهاد نمی‌شود
        if is_prerelease(latest):
            results.append({**base(e), "latest": e["pinned"], "drift": None,
                            "note": f"جدیدترین ({latest}) پیش‌انتشار است — نادیده گرفته شد"})
            continue

        drift = bump_kind(e["pinned"], latest) if newer(latest, e["pinned"]) else None
        results.append({**base(e), "latest": latest, "drift": drift, "note": ""})
    return results, errors


def base(e: dict) -> dict:
    return {"id": e["id"], "name": e["name"], "registry": e["registry"],
            "pinned": e["pinned"], "role": e.get("role", "")}


def report(results: list[dict], errors: list[dict]) -> None:
    majors = [r for r in results if r["drift"] == "major"]
    minors = [r for r in results if r["drift"] in ("minor", "patch")]
    fresh = [r for r in results if r["drift"] is None]

    print(f"بررسی‌شده: {len(results)}  ·  به‌روز: {len(fresh)}  ·  "
          f"عقب (minor/patch): {len(minors)}  ·  عقب (major): {len(majors)}")
    if errors:
        print(f"خوانده نشد: {len(errors)}")

    for title, rows in (("⛔ پرشِ نسخه‌ی اصلی — مهاجرت لازم دارد", majors),
                        ("· عقب‌افتادگیِ کوچک — مکانیکی", minors)):
        if not rows:
            continue
        print(f"\n{title}")
        for r in rows:
            print(f"   {r['name']:<28} {r['pinned']:>10} → {r['latest']:<10} {r['role']}")

    for r in results:
        if r["note"]:
            print(f"\nℹ️  {r['name']}: {r['note']}")
    for e in errors:
        print(f"\n⚠️  {e['id']}: {e['error']}")


def write_back(stack: dict, results: list[dict], allow_major: bool) -> int:
    by_id = {r["id"]: r for r in results}
    changed = 0
    for e in stack["entries"]:
        r = by_id.get(e["id"])
        if not r or r["drift"] is None:
            continue
        if r["drift"] == "major" and not allow_major:
            continue
        e["pinned"] = r["latest"]
        changed += 1
    if changed:
        stack["checked_at"] = datetime.date.today().isoformat()
        with open(STACK, "w", encoding="utf-8") as f:
            json.dump(stack, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description="سنجشِ عقب‌افتادگیِ نسخه‌های دستورالعمل")
    ap.add_argument("--json", action="store_true", help="خروجیِ ماشینی")
    ap.add_argument("--write", action="store_true", help="پین‌ها را در stack.json به‌روز کن")
    ap.add_argument("--allow-major", action="store_true", help="با --write پرشِ اصلی را هم بنویس")
    args = ap.parse_args()

    try:
        with open(STACK, encoding="utf-8") as f:
            stack = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"stack.json خوانده نشد: {exc}", file=sys.stderr)
        return 3

    results, errors = check(stack)
    if not results and errors:
        print("هیچ ورودی‌ای خوانده نشد — احتمالاً شبکه قطع است.", file=sys.stderr)
        return 3

    wrote = write_back(stack, results, args.allow_major) if args.write else 0

    if args.json:
        json.dump({"guideline_version": stack.get("guideline_version"),
                   "results": results, "errors": errors, "written": wrote},
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        report(results, errors)
        if wrote:
            print(f"\n✍️  {wrote} پین در stack.json به‌روز شد.")

    if any(r["drift"] == "major" for r in results):
        return 2
    if any(r["drift"] for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
