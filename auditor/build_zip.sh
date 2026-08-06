#!/bin/bash
# ساختِ بسته‌ی قابلِ آپلودِ پنل — فقط فایل‌هایی که باید روی سرور بروند.
# از ریشه‌ی پروژه اجرا کن:  bash auditor/build_zip.sh
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/panel"
OUT="$ROOT/modland-panel.zip"
FILES="index.html sw.js h2c.js manifest.json font1.woff2 font2.woff2 \
img1.png img2.png img3.png img4.png icon-192.png icon-512.png icon-maskable.png"

TMP="$(mktemp -d)"
mkdir -p "$TMP/modland"
for f in $FILES; do
  if [ -f "$SRC/$f" ]; then cp "$SRC/$f" "$TMP/modland/"
  else echo "❌ نبود: $f"; exit 1; fi
done
rm -f "$OUT"
( cd "$TMP" && zip -qr "$OUT" modland )
rm -rf "$TMP"
echo "بسته ساخته شد: $OUT — $(unzip -l "$OUT" | tail -1 | awk '{print $2}') فایل"
echo "یادت باشد نسخه‌ی کش در panel/sw.js را قبلش جلو ببری."
