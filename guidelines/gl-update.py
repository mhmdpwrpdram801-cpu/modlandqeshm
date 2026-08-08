#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
گرفتنِ نسخه‌ی تازه‌ی دستورالعمل از منبعِ رسمی.

مسئله‌ای که حل می‌کند: وقتی این بسته در چند پروژه کپی شده، هر کپی جدا کهنه
می‌شود و کسی خبردار نمی‌شود. `lock.json` می‌گوید «کدِ من از دستورالعمل عقب
است»، ولی نمی‌گوید «دستورالعملِ من از منبع عقب است». این اسکریپت همان را می‌گوید
و خودش می‌آوردش.

  python3 guidelines/gl-update.py                    # بسنج، چیزی را عوض نکن
  python3 guidelines/gl-update.py --apply            # سندها را به‌روز کن
  python3 guidelines/gl-update.py --apply --with-tools   # اسکریپت‌ها و هوک را هم
  python3 guidelines/gl-update.py --json             # خروجیِ ماشینی (برای CI و هوک)

کدِ خروجی:
  0 = به‌روز است
  1 = نسخه‌ی تازه‌تری در منبع هست
  3 = خطا (شبکه، پیکربندی، …)

سه قاعده‌ی سختِ این فایل:
  ۱. `lock.json` هیچ‌وقت از منبع نمی‌آید — مُهرِ انطباقِ همین پروژه است (MIG-07).
  ۲. فایلی که محلی دست‌کاری شده بی‌صدا رونویسی نمی‌شود؛ `--force` می‌خواهد.
  ۳. در خودِ مخزنِ منبع (`is_origin`) اصلاً چیزی نمی‌نویسد.

هیچ وابستگیِ بیرونی ندارد — فقط کتابخانه‌ی استانداردِ پایتون ۳.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOURCE = os.path.join(HERE, "source.json")
BASELINE = os.path.join(HERE, ".upstream.json")     # هشِ آخرین همگام‌سازی
CACHE = os.path.join(HERE, ".upstream-cache.json")  # برای هوک؛ محلی و گیت‌ایگنور

TIMEOUT = 25
UA = "modland-guideline-update/1"
VERSION_RE = re.compile(r"^\*\*نسخه: `([^`]+)`\*\*", re.M)


def vkey(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _norm_repo(url: str) -> str:
    """`git@github.com:a/b.git` و `https://github.com/A/B` → `a/b`."""
    u = url.strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    u = re.sub(r"^[a-z+]+://", "", u)          # https:// ، ssh:// …
    u = re.sub(r"^[^@/]+@", "", u)             # git@
    u = u.replace(":", "/", 1) if "/" not in u.split(":")[0] else u
    parts = [p for p in u.split("/") if p]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else ""


def is_origin_repo(cfg: dict) -> bool:
    """آیا همین‌جا خودِ مخزنِ منبع است؟

    عمداً **تشخیص داده می‌شود، نه اعلام**: اگر آدم باید دستی `is_origin` را
    false می‌کرد، اولین چیزی بود که یادش می‌رفت — و آن‌وقت پروژه بی‌صدا هیچ
    به‌روزرسانی‌ای نمی‌گرفت و کسی هم نمی‌فهمید. مقایسه‌ی remoteهای گیت با
    نشانیِ منبع این را خودکار می‌کند.

    `is_origin` اگر بولی باشد همان برنده است (درِ فرار برای حالت‌های عجیب).
    اگر گیت نبود یا خطا داد، «کپی» فرض می‌شود: کپی به‌روزرسانی می‌گیرد، و
    این بی‌خطرتر از مخزنی است که هیچ‌وقت به‌روز نمی‌شود.
    """
    override = cfg.get("is_origin")
    if isinstance(override, bool):
        return override

    origin = cfg.get("origin", {})
    want = f"{origin.get('owner', '')}/{origin.get('repo', '')}".lower()
    if not want.strip("/"):
        return False
    try:
        out = subprocess.run(["git", "-C", ROOT, "remote", "-v"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    if out.returncode != 0:
        return False
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and _norm_repo(parts[1]) == want:
            return True
    return False


def dirty_bundle(cfg: dict) -> list[str]:
    """فایل‌های بسته که کامیت‌نشده عوض شده‌اند.

    محافظِ آخر: اگر کسی وسطِ کار روی همین فایل‌ها باشد، به‌روزرسانی نباید
    کارش را ببلعد — حتی اگر تشخیصِ «منبع» به هر دلیلی اشتباه شده باشد.
    """
    paths = [e["path"] for e in cfg.get("files", [])]
    try:
        out = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--", *paths],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [ln[3:].strip() for ln in out.stdout.splitlines() if ln.strip()]


def base_url(origin: dict) -> str:
    if origin.get("kind") != "github-raw":
        raise RuntimeError(f"نوعِ منبعِ ناشناخته: {origin.get('kind')}")
    return (f"https://raw.githubusercontent.com/{origin['owner']}/"
            f"{origin['repo']}/{origin['ref']}/")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def local_version() -> str | None:
    try:
        with open(os.path.join(HERE, "FULLSTACK.md"), encoding="utf-8") as f:
            m = VERSION_RE.search(f.read())
        return m.group(1) if m else None
    except OSError:
        return None


def remote_version(base: str) -> str:
    m = VERSION_RE.search(fetch(base + "guidelines/FULLSTACK.md").decode("utf-8"))
    if not m:
        raise RuntimeError("نسخه در FULLSTACK.mdِ منبع پیدا نشد")
    return m.group(1)


def plan(cfg: dict, base: str) -> list[dict]:
    """برای هر فایل: محلی چیست، منبع چیست، دست‌کاری شده یا نه."""
    baseline = read_json(BASELINE, {}) or {}
    never = set(cfg.get("never_touch", []))
    out = []
    for entry in cfg["files"]:
        rel = entry["path"]
        if rel in never:
            continue
        local_path = os.path.join(ROOT, rel)
        try:
            remote_bytes = fetch(base + rel)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                # در منبع نیست (هنوز اضافه نشده، یا از بسته درآمده). این خطا نیست؛
                # وگرنه پروژه‌ها برای همیشه یک خطای بی‌معنی نشان می‌دهند.
                out.append({"path": rel, "kind": entry["kind"], "state": "در منبع نیست",
                            "detail": ""})
                continue
            out.append({"path": rel, "kind": entry["kind"], "state": "خطا",
                        "detail": f"HTTP {exc.code}"})
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            out.append({"path": rel, "kind": entry["kind"], "state": "خطا",
                        "detail": f"{type(exc).__name__}: {exc}"})
            continue

        try:
            with open(local_path, "rb") as f:
                local_bytes = f.read()
        except OSError:
            local_bytes = None

        if local_bytes is None:
            state = "تازه"
        elif sha(local_bytes) == sha(remote_bytes):
            state = "یکی"
        elif baseline.get(rel) and baseline[rel] != sha(local_bytes):
            state = "دست‌کاری‌شده"
        else:
            state = "عقب"

        out.append({"path": rel, "kind": entry["kind"], "state": state,
                    "remote": remote_bytes, "detail": ""})
    return out


def apply(rows: list[dict], with_tools: bool, force: bool) -> tuple[int, list[str]]:
    baseline = read_json(BASELINE, {}) or {}
    written, skipped = 0, []
    for r in rows:
        if r["state"] in ("یکی", "خطا", "در منبع نیست"):
            continue
        if r["kind"] == "tool" and not with_tools:
            skipped.append(f"{r['path']} (ابزار — با --with-tools)")
            continue
        if r["state"] == "دست‌کاری‌شده" and not force:
            skipped.append(f"{r['path']} (محلی عوض شده — با --force)")
            continue
        dest = os.path.join(ROOT, r["path"])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(r["remote"])
        if r["path"].endswith(".py"):
            os.chmod(dest, 0o755)
        baseline[r["path"]] = sha(r["remote"])
        written += 1
    if written:
        baseline["_synced_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
    return written, skipped


def write_cache(lv: str | None, rv: str | None, error: str = "") -> None:
    """هوک این را می‌خواند تا شروعِ نشست منتظرِ شبکه نماند."""
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump({"checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       "local": lv, "remote": rv, "error": error},
                      f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="گرفتنِ نسخه‌ی تازه‌ی دستورالعمل از منبع")
    ap.add_argument("--apply", action="store_true", help="واقعاً بنویس")
    ap.add_argument("--with-tools", action="store_true", help="اسکریپت‌ها و هوک را هم به‌روز کن")
    ap.add_argument("--force", action="store_true", help="فایلِ دست‌کاری‌شده را هم رونویسی کن")
    ap.add_argument("--json", action="store_true", help="خروجیِ ماشینی")
    args = ap.parse_args()

    cfg = read_json(SOURCE)
    if not cfg:
        print("guidelines/source.json خوانده نشد.", file=sys.stderr)
        return 3

    lv = local_version()

    try:
        base = base_url(cfg["origin"])
        rv = remote_version(base)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError, KeyError, RuntimeError) as exc:
        msg = f"{type(exc).__name__}: {exc}"
        write_cache(lv, None, msg)
        if args.json:
            json.dump({"ok": False, "local": lv, "error": msg}, sys.stdout, ensure_ascii=False)
            print()
        else:
            print(f"منبع خوانده نشد — {msg}", file=sys.stderr)
        return 3

    write_cache(lv, rv)
    behind = bool(lv and rv and vkey(rv) > vkey(lv))

    if is_origin_repo(cfg):
        if args.json:
            json.dump({"ok": True, "is_origin": True, "local": lv, "remote": rv, "behind": False},
                      sys.stdout, ensure_ascii=False)
            print()
        else:
            print(f"این خودِ مخزنِ منبع است (نسخه {lv}) — چیزی از بیرون گرفته نمی‌شود.")
            if behind:
                print("⚠️  ولی نسخه‌ی روی شاخه‌ی منبع جلوتر است؛ یعنی کارِ کامیت‌نشده داری.")
        return 0

    if not behind and not args.apply:
        if args.json:
            json.dump({"ok": True, "local": lv, "remote": rv, "behind": False},
                      sys.stdout, ensure_ascii=False)
            print()
        else:
            print(f"دستورالعمل به‌روز است (نسخه {lv}).")
        return 0

    dirty = dirty_bundle(cfg)
    if dirty and args.apply and not args.force:
        print("این فایل‌های بسته کامیت‌نشده عوض شده‌اند — اول کامیتشان کن "
              "(یا --force):", file=sys.stderr)
        for d in dirty:
            print(f"   {d}", file=sys.stderr)
        return 3

    rows = plan(cfg, base)
    errors = [r for r in rows if r["state"] == "خطا"]
    changed = [r for r in rows if r["state"] in ("عقب", "تازه", "دست‌کاری‌شده")]

    if args.apply:
        written, skipped = apply(rows, args.with_tools, args.force)
    else:
        written, skipped = 0, []

    if args.json:
        json.dump({"ok": not errors, "local": lv, "remote": rv, "behind": behind,
                   "written": written, "skipped": skipped,
                   "changed": [{"path": r["path"], "kind": r["kind"], "state": r["state"]}
                               for r in changed],
                   "errors": [{"path": r["path"], "detail": r["detail"]} for r in errors]},
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print(f"محلی: {lv}  ·  منبع: {rv}" + ("  ← عقب افتاده‌ای" if behind else ""))
        if changed:
            print(f"\n{len(changed)} فایل فرق دارد:")
            for r in changed:
                print(f"   [{r['kind']:<4}] {r['state']:<12} {r['path']}")
        if written:
            print(f"\n✍️  {written} فایل نوشته شد.")
        for s in skipped:
            print(f"   رد شد: {s}")
        for e in errors:
            print(f"   ⚠️  {e['path']}: {e['detail']}")
        if written:
            print("\nحالا مُهرِ lock.json هنوز روی نسخه‌ی قبلی است — این عمدی است (MIG-07).")
            print("گامِ بعد: /gl-migrate")

    return 1 if behind else 0


if __name__ == "__main__":
    sys.exit(main())
