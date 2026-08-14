# راهنمای این مخزن برای Claude Code

کاربر فارسی‌زبان است — **فارسی جواب بده**.

## دو منبعی که باید بخوانی

@README-FOR-CLAUDE-CODE.md

@guidelines/FULLSTACK.md

## ترتیبِ اولویت

1. **حرفِ صریحِ کاربر در همین گفت‌وگو**
2. **`README-FOR-CLAUDE-CODE.md`** — قاعده‌های همین پروژه. برای ربات، `bot/README.md`.
3. **`guidelines/lock.json` → `waivers`** — انحراف‌های عمدی و تأییدشده
4. **`guidelines/FULLSTACK.md`** — دستورالعملِ عمومیِ فول‌استک
5. پیش‌فرض‌های عمومیِ خودت

دستورالعملِ فول‌استک **عمومی** است و این پروژه **خاص**. جایی که تناقض دیدی،
قاعده‌ی پروژه برنده است. پنلِ تک‌فایلِ بدونِ فریم‌ورک یک تصمیمِ آگاهانه است، نه
بدهیِ فنی — «مدرن‌سازی»اش نکن (`waiver: panel-no-framework`).

## قبل از هر تحویل

```bash
python3 auditor/audit.py panel/index.html -c auditor/audit.config.json   # باید ۰ برگرداند
python3 auditor/audit.py expenses/index.html -c expenses/audit.config.json  # اگر expenses/ را دست زدی
python3 auditor/server_audit.py                                           # اگر bot/ را دست زدی
deno run -A --import-map auditor/botsim/import_map.json auditor/botsim/run.ts   # همچنین
python3 guidelines/self-check.py                                          # اگر guidelines/ را دست زدی
```

هر چهارتا در `.github/workflows/gates.yml` روی هر PR هم اجرا می‌شوند، ولی **قبل از
push خودت بزنشان** — دروازه‌ای که ده دقیقه بعد قرمز می‌دهد جای دیدنِ باگ را نمی‌گیرد.

## دستورهای دستورالعمل

| دستور | کار |
|-------|-----|
| `/gl-check` | اختلافِ کدِ فعلی با دستورالعمل (بدونِ تغییر) |
| `/gl-migrate` | اجرای مهاجرت‌های معلق روی کدِ موجود |
| `/gl-sync` | به‌روزرسانیِ خودِ دستورالعمل |

نسخه‌ی فعالِ دستورالعمل و مهاجرتِ معلق را هوکِ `.claude/hooks/guideline-boot.py`
در شروعِ هر نشست خودش اعلام می‌کند.
