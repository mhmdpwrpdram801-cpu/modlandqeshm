#!/usr/bin/env python3
"""مولدِ جهشِ مکانیکی — جهش‌هایی که کسی انتخابشان نکرده.

جهش‌های دست‌چینِ `mutants.py` از باگ‌هایی می‌آیند که **می‌شناسیم**، و بررسی‌شان هم
از قبل نوشته شده؛ طبیعی است که گرفته شوند. آن عدد می‌گوید حافظه‌مان خوب است، نه
اینکه دروازه قوی است.

اینجا هیچ انتخابی در کار نیست: عملگرها روی خودِ متنِ کد راه می‌روند و هر جا
الگویشان بخورد جهش می‌سازند. هرچه در برود، جایی است که اصلاً به آن فکر نکرده‌ایم.

    python3 auditor/mutgen.py panel/index.html -n 40 --seed 1 -o /tmp/gen.json
    python3 auditor/mutants.py --from /tmp/gen.json -j 4

قاعده‌ی یکتایی: هر جهش باید **دقیقاً یک** تطابق در فایل داشته باشد، وگرنه ساخته
نمی‌شود. متنِ اطراف آن‌قدر بزرگ می‌شود تا یکتا شود.
"""
import argparse, json, random, re, sys

# (نام، الگو، تابعِ جایگزین، قاعده‌ی مرتبط)
OPS = [
    ("مقایسه: >= به >",   re.compile(r">="),            lambda m: ">",     "DATA-03/TEST-06"),
    ("مقایسه: <= به <",   re.compile(r"<="),            lambda m: "<",     "DATA-03/TEST-06"),
    ("مقایسه: > به >=",   re.compile(r"(?<![-=<>!])>(?![=>])"), lambda m: ">=", "TEST-06"),
    ("برابری: === به !==", re.compile(r"==="),          lambda m: "!==",   "CORE-01"),
    ("منطق: && به ||",    re.compile(r"&&"),            lambda m: "||",    "CORE-01"),
    ("منطق: || به &&",    re.compile(r"\|\|"),          lambda m: "&&",    "CORE-01"),
    ("حذفِ await",        re.compile(r"\bawait\s+"),    lambda m: "",      "ARCH-06/OPS-03"),
    ("حذفِ esc()",        re.compile(r"\besc\("),       lambda m: "String(", "SEC-04"),
    ("حذفِ trim()",       re.compile(r"\.trim\(\)"),    lambda m: "",      "API-07"),
    ("عددِ ثابت +۱",      re.compile(r"(?<![\w.])(\d{1,6})(?![\w.])"),
                          lambda m: str(int(m.group(1)) + 1),             "TEST-06"),
    ("نقیضِ شرطِ if",     re.compile(r"\bif\("),        lambda m: "if(!",  "CORE-01"),
]


# این فایل HTML و CSS را هم داخلِ رشته‌های جاوااسکریپت دارد. جهش روی آن‌ها
# جهشِ منطقی نیست: عوض کردنِ `>` در `</div>` فقط نشانه‌گذاری را خراب می‌کند و
# ۱۸px که ۱۹px شود هیچ ادعایی درباره‌ی دروازه نمی‌سازد. اینها کنار گذاشته
# می‌شوند تا عددِ خروجی سیگنال باشد نه نویز.
# (تشخیص متن‌محور است، نه با تجزیه‌گرِ واقعی — پس محافظه‌کار است و ممکن است
#  چند جهشِ سالم را هم رد کند. این بهتر از قبولِ نویز است.)
TAGISH = re.compile(r"</|<[a-zA-Z][\w-]*[\s/>]|&[a-z]+;")
CSSISH = re.compile(r"(px|em|rem|%|vh|vw|deg|ms)\b|font-|color|margin|padding|border|width|height|#[0-9a-fA-F]{3,6}")


def noisy(app, m, name):
    a, b = max(0, m.start() - 40), min(len(app), m.end() + 40)
    win = app[a:b]
    if TAGISH.search(win):
        return True
    if name.startswith("عددِ ثابت") and CSSISH.search(win):
        return True
    return False


def comment_spans(js):
    """بازه‌های کامنت. جهش داخلِ کامنت هیچ رفتاری را عوض نمی‌کند و فقط عدد را
    خراب می‌کند — دو تا در نمونه‌ی اول همین‌طور «در رفتند» بی‌آنکه باگی باشند."""
    spans, i, n = [], 0, len(js)
    while i < n:
        c = js[i]
        if c in "\"'`":                      # از رشته رد شو تا // داخلِ رشته را کامنت نگیریم
            q, i = c, i + 1
            while i < n and js[i] != q:
                i += 2 if js[i] == "\\" else 1
            i += 1
        elif js.startswith("//", i):
            j = js.find("\n", i); j = n if j < 0 else j
            spans.append((i, j)); i = j
        elif js.startswith("/*", i):
            j = js.find("*/", i + 2); j = n if j < 0 else j + 2
            spans.append((i, j)); i = j
        else:
            i += 1
    return spans


def enclosing(js, pos):
    """نامِ تابعی که جهش داخلش افتاده — تا بشود دید کدام ناحیه‌ها بی‌پوشش‌اند."""
    best = ""
    for m in re.finditer(r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|"
                         r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", js):
        if m.start() > pos:
            break
        best = m.group(1) or m.group(2) or best
    return best


def biggest_script(src):
    """بزرگ‌ترین اسکریپتِ درون‌خطی — یا خودِ فایل، اگر HTML نباشد (مثلِ bot/index.ts)."""
    blocks = [(m.start(1), m.group(1))
              for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", src, re.S | re.I)]
    if not blocks:
        return (0, src)
    return max(blocks, key=lambda b: len(b[1]))


def unique_window(src, pos, end, repl):
    """کوچک‌ترین پنجره‌ای که دقیقاً یک بار در فایل بیاید."""
    for pad in (14, 30, 60, 120, 240):
        a, b = max(0, pos - pad), min(len(src), end + pad)
        find = src[a:b]
        if src.count(find) == 1:
            return find, src[a:pos] + repl + src[end:b]
    return None, None


def generate(path, n, seed):
    src = open(path, encoding="utf-8").read()
    off, app = biggest_script(src)
    rnd = random.Random(seed)

    cspans = comment_spans(app)
    in_comment = lambda i: any(a <= i < b for a, b in cspans)

    sites = []
    for name, pat, fn, rule in OPS:
        for m in pat.finditer(app):
            if noisy(app, m, name) or in_comment(m.start()):
                continue
            sites.append((name, rule, off + m.start(), off + m.end(), fn(m)))
    rnd.shuffle(sites)

    out, seen, i = [], set(), 0
    for name, rule, pos, end, repl in sites:
        if len(out) >= n:
            break
        if src[pos:end] == repl:
            continue                                  # جایگزینی که چیزی عوض نمی‌کند
        find, new = unique_window(src, pos, end, repl)
        if find is None or find in seen:
            continue
        seen.add(find)
        i += 1
        snip = re.sub(r"\s+", " ", src[max(0, pos - 26):end + 26]).strip()
        fnname = enclosing(app, pos - off)
        out.append(dict(
            id=f"G{i:02d}", file=path, rule=rule, count=1, fn=fnname,
            desc=f"{name} @{fnname or '؟'} — …{snip[:64]}…",
            find=find, repl=new))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("-n", type=int, default=40, help="چند جهش")
    ap.add_argument("--seed", type=int, default=1, help="برای تکرارپذیری")
    ap.add_argument("-o", "--out", default="/tmp/gen-mutants.json")
    a = ap.parse_args()
    ms = generate(a.html, a.n, a.seed)
    json.dump(ms, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"{len(ms)} جهش ساخته شد → {a.out}  (seed={a.seed})")
    from collections import Counter
    for k, v in Counter(m["desc"].split(" — ")[0] for m in ms).most_common():
        print(f"  {v:3}  {k}")


if __name__ == "__main__":
    main()
