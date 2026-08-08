#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
به‌روزرسانِ خودکارِ بخشِ «پشته» در CLAUDE.md.

نسخه‌های پایدارِ ابزارهای پشته را از منابعِ رسمی می‌گیرد، جدول را بازنویسی می‌کند،
و مقدارهای پین‌شده در خودِ مخزن (wrangler.toml و deploy.yml) را با آن‌ها می‌سنجد.

    python3 scripts/update_stack.py            # بگیر و بنویس
    python3 scripts/update_stack.py --check    # فقط گزارش بده، فایل را دست نزن
    python3 scripts/update_stack.py --offline  # بدونِ شبکه، فقط سنجشِ رانش

کدِ خروجی:
    ۰  چیزی برای تغییر نبود
    ۱۰ سند عوض شد یا رانشی هست (در --check یعنی «باید به‌روزرسانی شود»)
    ۱  خطا

قاعده‌ی مهم: اگر منبعی جواب نداد، مقدارِ قبلیِ همان ردیف از خودِ CLAUDE.md
برداشته می‌شود. یک قطعیِ شبکه نباید سند را خراب کند.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "CLAUDE.md"
SOURCES = Path(__file__).resolve().parent / "stack_sources.json"

BEGIN = "<!-- STACK:BEGIN — این بخش خودکار نوشته می‌شود؛ دستی ویرایشش نکن -->"
END = "<!-- STACK:END -->"

TIMEOUT = 25
UA = "modlandqeshm-stack-updater (+https://github.com/mhmdpwrpdram801-cpu/modlandqeshm)"

# ────────────────────────────────────────────────────────────── ابزارِ شبکه


class Unreachable(Exception):
    """منبع در دسترس نبود — با دلیلی که به‌دردِ خواننده بخورد."""


def fetch_json(url: str, attempts: int = 3) -> object:
    """
    JSON بگیر، با تلاشِ دوباره برای خطاهای گذرا.

    ۴۰۳/۴۰۴ گذرا نیستند و تکرار نمی‌شوند؛ قطعیِ شبکه و ۵xx تکرار می‌شوند.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    token = os.environ.get("GITHUB_TOKEN", "")
    if token and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {token}")

    last = ""
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                if "api.github.com" in url:
                    # چه توکن نباشد و چه توکنِ محدود باشد، حرفِ آخر یکی است.
                    raise Unreachable("گیت‌هاب در این محیط باز نیست؛ در CI پر می‌شود") from e
                raise Unreachable(f"HTTP {e.code}") from e
            last = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            last = type(e).__name__
        if i < attempts - 1:
            time.sleep(2 ** i)
    raise Unreachable(last or "در دسترس نبود")


def today() -> dt.date:
    return dt.date.today()


def parse_date(value: object) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


# ────────────────────────────────────────────────────── گرفتنِ نسخه از منابع


def from_npm(pkg: str) -> tuple[str, str]:
    """آخرین نسخه‌ی پایدارِ یک بسته‌ی npm (تگِ latest، یعنی بدونِ pre-release)."""
    data = fetch_json(f"https://registry.npmjs.org/{pkg}/latest")
    return str(data["version"]), ""


def from_eol(product: str, prefer: str = "") -> tuple[str, str]:
    """
    نسخه‌ی توصیه‌شده از endoflife.date.

    prefer=="lts" → تازه‌ترین چرخه‌ای که *همین حالا* LTS است (تاریخِ lts گذشته باشد).
    وگرنه → تازه‌ترین چرخه‌ای که هنوز پشتیبانی می‌شود.
    """
    cycles = fetch_json(f"https://endoflife.date/api/{product}.json")
    if not isinstance(cycles, list) or not cycles:
        raise ValueError(f"پاسخِ نامنتظر برای {product}")

    now = today()

    def alive(c: dict) -> bool:
        eol = c.get("eol")
        if eol is False:
            return True
        d = parse_date(eol)
        return d is None or d > now

    def is_lts_now(c: dict) -> bool:
        d = parse_date(c.get("lts"))
        return d is not None and d <= now

    pool = [c for c in cycles if isinstance(c, dict) and alive(c)]
    chosen = None
    if prefer == "lts":
        chosen = next((c for c in pool if is_lts_now(c)), None)
    if chosen is None:
        chosen = pool[0] if pool else cycles[0]

    version = str(chosen.get("latest") or chosen.get("cycle") or "?")
    eol = chosen.get("eol")
    extra = f"پایانِ پشتیبانی {eol}" if isinstance(eol, str) else ""
    return version, extra


def from_github(repo: str) -> tuple[str, str]:
    """تگِ آخرین ریلیزِ یک مخزنِ گیت‌هاب."""
    data = fetch_json(f"https://api.github.com/repos/{repo}/releases/latest")
    return str(data["tag_name"]), ""


def resolve(item: dict) -> tuple[str, str]:
    kind = item.get("kind")
    if kind == "npm":
        return from_npm(item["id"])
    if kind == "eol":
        return from_eol(item["id"], item.get("prefer", ""))
    if kind == "gh":
        return from_github(item["id"])
    raise ValueError(f"نوعِ ناشناخته: {kind!r}")


# ──────────────────────────────────────────────── خواندنِ مقدارهای قبلیِ سند


ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|([^|]*)\|([^|]*)\|", re.M)


def previous_values(doc_text: str) -> dict[str, str]:
    """
    مقدارهای جدولِ فعلی را برمی‌دارد تا اگر منبعی جواب نداد، به‌جای خالی‌کردنِ
    ردیف همان مقدارِ قبلی بماند. کلیدِ هر ردیف در ستونِ اولِ جدول (`key`) است.
    """
    block = extract_block(doc_text)
    if block is None:
        return {}
    out: dict[str, str] = {}
    for m in ROW.finditer(block):
        key, _label, version = m.group(1), m.group(2), m.group(3)
        value = version.strip().strip("`")
        # جای‌نگه‌دارها مقدارِ قبلی نیستند؛ وگرنه یک بارِ ناموفق برای همیشه می‌ماسد.
        if value and value not in ("؟", "—", "?"):
            out[key.strip()] = value
    return out


def extract_block(doc_text: str) -> str | None:
    i = doc_text.find(BEGIN)
    j = doc_text.find(END)
    if i == -1 or j == -1 or j < i:
        return None
    return doc_text[i + len(BEGIN) : j]


# ───────────────────────────────────────────── سنجشِ رانشِ مقدارهای پین‌شده


def workerd_to_compat_date(version: str) -> str | None:
    """نسخه‌ی workerd به شکلِ 1.YYYYMMDD.0 است — تاریخِ سازگاری از همان درمی‌آید."""
    m = re.match(r"^\d+\.(\d{4})(\d{2})(\d{2})\.", version)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def known(value: str) -> str:
    """مقدارِ واقعی یا رشته‌ی خالی — با جای‌نگه‌دار نباید رانش سنجید."""
    return "" if value in ("", "—", "؟", "?") else value


def check_drift(cfg: dict, versions: dict[str, str]) -> list[str]:
    """ایرادهایی که آدم باید ببیند: پینِ کهنه در مخزن نسبت به نسخه‌ی پایدارِ امروز."""
    d = cfg.get("drift", {})
    notes: list[str] = []

    # ۱) compatibility_date در wrangler.toml
    wt = ROOT / d.get("wrangler_toml", "wrangler.toml")
    workerd = known(versions.get("workerd", ""))
    if wt.is_file():
        text = wt.read_text(encoding="utf-8")
        m = re.search(r'compatibility_date\s*=\s*"(\d{4}-\d{2}-\d{2})"', text)
        latest_compat = workerd_to_compat_date(workerd) if workerd else None
        if m and latest_compat:
            have = parse_date(m.group(1))
            newest = parse_date(latest_compat)
            max_age = int(d.get("compat_date_max_age_days", 180))
            if have and newest and (newest - have).days > max_age:
                notes.append(
                    f"`compatibility_date` در wrangler.toml روی {m.group(1)} است و "
                    f"{(newest - have).days} روز از workerd پایدار ({latest_compat}) عقب‌تر. "
                    "بالا بردنش رفتارِ ورکر را عوض می‌کند — با تست جلو برو."
                )

    # ۲) wranglerVersion پین‌شده در گردش‌کارِ انتشار
    wf = ROOT / d.get("deploy_workflow", ".github/workflows/deploy.yml")
    if wf.is_file():
        text = wf.read_text(encoding="utf-8")
        m = re.search(r"wranglerVersion:\s*'([^']+)'", text)
        latest = known(versions.get("wrangler", ""))
        if m and latest and m.group(1) != latest:
            notes.append(
                f"`wranglerVersion` در deploy.yml روی {m.group(1)} پین است، "
                f"پایدارِ فعلی {latest}."
            )
        m = re.search(r"actions/checkout@(v\d+)", text)
        gh_checkout = known(versions.get("checkout", ""))
        if m and gh_checkout:
            want = re.match(r"^v?(\d+)", gh_checkout.lstrip("v"))
            have = re.match(r"^v(\d+)$", m.group(1))
            if want and have and want.group(1) != have.group(1):
                notes.append(
                    f"`actions/checkout` روی {m.group(1)} است، ریلیزِ فعلی {gh_checkout}."
                )

    # ۳) قالبِ نسخه‌ی کشِ سرویس‌ورکر — نگهبانِ قاعده‌ی ۶ راهنما
    sw = ROOT / d.get("service_worker", "panel/sw.js")
    if sw.is_file():
        m = re.search(r"mlq-(\d{4}-\d{2}-\d{2})-(\d+)", sw.read_text(encoding="utf-8"))
        if not m:
            notes.append("نسخه‌ی کش در panel/sw.js با قالبِ `mlq-YYYY-MM-DD-NN` پیدا نشد.")

    return notes


# ───────────────────────────────────────────────────────── ساختنِ متنِ بلوک


def render(cfg: dict, versions: dict[str, str], extras: dict[str, str],
           stale: dict[str, str], drift: list[str]) -> str:
    stamp = today().isoformat()
    lines: list[str] = ["", f"> آخرین به‌روزرسانیِ خودکار: **{stamp}**", ""]

    for group in cfg.get("groups", []):
        lines.append(f"**{group['title']}**")
        lines.append("")
        lines.append("| کلید | ابزار | نسخه‌ی پایدار | یادداشت |")
        lines.append("| --- | --- | --- | --- |")
        for item in group.get("items", []):
            key = item["key"]
            version = versions.get(key, "؟")
            note = item.get("note", "")
            extra = extras.get(key, "")
            if extra:
                note = f"{note} — {extra}" if note else extra
            if key in stale:
                note = (note + " — " if note else "") + f"⚠️ {stale[key]}"
            lines.append(f"| `{key}` | {item['label']} | `{version}` | {note} |")
        lines.append("")

    compat = workerd_to_compat_date(versions.get("workerd", ""))
    if compat:
        lines.append(
            f"`compatibility_date` معادلِ workerd پایدار: **{compat}** — "
            "بالا بردنش در `wrangler.toml` یک تغییرِ رفتاری است، نه یک به‌روزرسانیِ ساده."
        )
        lines.append("")

    if drift:
        lines.append("**رانشِ مخزن نسبت به این نسخه‌ها:**")
        lines.append("")
        for n in drift:
            lines.append(f"- {n}")
        lines.append("")
    else:
        lines.append("رانشی بینِ پین‌های مخزن و نسخه‌های بالا دیده نشد.")
        lines.append("")

    lines.append(
        "این جدول توصیه است، نه دستورِ ارتقا. تا وقتی بازرس سبز است و کاربر ایرادی "
        "ندارد، عوض‌کردنِ نسخه‌ها به‌خودیِ‌خود ارزش ندارد."
    )
    lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────── اجرا


def main() -> int:
    ap = argparse.ArgumentParser(description="به‌روزرسانیِ جدولِ پشته در CLAUDE.md")
    ap.add_argument("--check", action="store_true", help="فقط گزارش، بدونِ نوشتن")
    ap.add_argument("--offline", action="store_true", help="بدونِ شبکه؛ مقدارهای فعلیِ سند")
    args = ap.parse_args()

    if not SOURCES.is_file():
        print(f"❌ فایلِ منابع نیست: {SOURCES}", file=sys.stderr)
        return 1
    if not DOC.is_file():
        print(f"❌ سند نیست: {DOC}", file=sys.stderr)
        return 1

    cfg = json.loads(SOURCES.read_text(encoding="utf-8"))
    doc_text = DOC.read_text(encoding="utf-8")
    if extract_block(doc_text) is None:
        print("❌ نشانه‌های STACK:BEGIN/END در CLAUDE.md پیدا نشد.", file=sys.stderr)
        return 1

    prev = previous_values(doc_text)
    versions: dict[str, str] = {}
    extras: dict[str, str] = {}
    stale: dict[str, str] = {}

    for group in cfg.get("groups", []):
        for item in group.get("items", []):
            key = item["key"]
            if args.offline:
                versions[key] = prev.get(key, "—")
                continue
            try:
                version, extra = resolve(item)
                versions[key] = version
                if extra:
                    extras[key] = extra
                print(f"  {key:<16} {version}")
            except (Unreachable, KeyError, ValueError) as e:
                fallback = prev.get(key, "")
                reason = str(e) or type(e).__name__
                versions[key] = fallback or "—"
                stale[key] = (f"{reason} — مقدارِ قبلی نگه داشته شد"
                              if fallback else reason)
                print(f"  {key:<16} ⚠️ {reason}"
                      + (f" (مقدارِ قبلی: {fallback})" if fallback else ""),
                      file=sys.stderr)

    drift = check_drift(cfg, versions)

    print()
    if drift:
        print("رانش:")
        for n in drift:
            print(f"  · {re.sub(r'`', '', n)}")
    else:
        print("رانشی دیده نشد.")

    # آفلاین چیزی تازه نگرفته. اگر بنویسد فقط سند را با مقدارهای ناقص فقیر می‌کند
    # و تاریخِ امروز را هم دروغ به آن می‌چسباند — پس فقط رانش را گزارش می‌کند.
    if args.offline:
        print("\n(حالتِ آفلاین: سند دست نخورد.)")
        return 10 if drift else 0

    block = render(cfg, versions, extras, stale, drift)
    new_text = doc_text[: doc_text.find(BEGIN) + len(BEGIN)] + block + doc_text[doc_text.find(END):]
    changed = new_text != doc_text

    if args.check:
        print("\n" + ("سند به‌روزرسانی لازم دارد." if changed else "سند به‌روز است."))
        return 10 if (changed or drift) else 0

    if changed:
        DOC.write_text(new_text, encoding="utf-8")
        print("\n✅ CLAUDE.md به‌روزرسانی شد.")
        return 10

    print("\n✅ چیزی عوض نشد.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
