---
description: اجرای کاملِ دروازه‌ی تحویل و گزارشِ صادقانه‌ی نتیجه
allowed-tools: Bash(python3 auditor/audit.py:*), Bash(git status:*), Bash(git diff:*), Read, Glob, Grep
---

دروازه‌ی تحویلِ بخشِ ۴ فایلِ `CLAUDE.md` را کامل اجرا کن. میان‌بر نزن و هیچ مرحله‌ای
را «احتمالاً درست است» فرض نکن.

۱. بازرس، اجرای عادی:

```
python3 auditor/audit.py panel/index.html -c auditor/audit.config.json
```

۲. تکرارپذیری (نتیجه‌ی شانسی را لو می‌دهد):

```
python3 auditor/audit.py panel/index.html -c auditor/audit.config.json -r 3
```

۳. موتورِ سافاری، چون کاربر آیفون هم دارد:

```
python3 auditor/audit.py panel/index.html -c auditor/audit.config.json -e webkit
```

۴. اگر `panel/index.html` در این تغییر عوض شده، وارسی کن نسخه‌ی کشِ `panel/sw.js`
   هم جلو رفته باشد (`mlq-YYYY-MM-DD-NN`). اگر نرفته، خودت جلو ببر.

۵. `git status` و `git diff` را نگاه کن: چیزی که نباید کامیت شود جا نمانده باشد
   (فایلِ موقت، کدِ اشکال‌زدایی، رمز).

۶. چند تا از عکس‌های `/tmp/audit_shots` را با ابزارِ Read واقعاً **ببین**، نه اینکه
   فقط وجودشان را تأیید کنی.

بعد یک گزارشِ کوتاه بده:

- هر سه اجرا سبز شدند یا نه، با کدِ خروجی.
- اگر باگی حل شده: کدام بررسیِ خودکار برایش اضافه شد و ثابت کن که قبلِ اصلاح
  fail می‌داده. اگر بررسی اضافه نشده، **صریح بگو که نشده و چرا**.
- چه چیزی را نتوانستی وارسی کنی.

اگر هر مرحله قرمز شد، همان‌جا بایست و بگو کدام و چرا. **تحویلِ سبزنشده ممنوع.**
