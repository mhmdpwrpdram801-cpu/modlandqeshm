#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بازرسِ عمومیِ اپلیکیشن‌های وب — یک موتور برای همه‌ی پروژه‌ها.

  python3 audit.py <index.html>                    # بدونِ تنظیمات هم کار می‌کند
  python3 audit.py <index.html> -c config.json     # با تنظیماتِ پروژه
  python3 audit.py <index.html> --json out.json    # گزارشِ ماشین‌خوان برای CI
  python3 audit.py <index.html> --only a11y,forms  # فقط چند بخش
  python3 audit.py <index.html> --skip shots       # همه به‌جزِ چند بخش
  python3 audit.py --list                          # فهرستِ بخش‌ها

خروجی: کدِ ۰ یعنی آماده‌ی تحویل، ۱ یعنی ایراد دارد.
"""
import sys, os, re, json, time, shutil, argparse, subprocess, threading, functools
import http.server, socketserver

HERE = os.path.dirname(os.path.abspath(__file__))

# ═════════════════════════════ گزارش
RESULTS = []            # [{section, level, key, msg}]
TIMINGS = []            # [{id, title, seconds}]
SECTIONS_RUN = []       # idهایی که واقعاً اجرا شدند
_CUR = ['عمومی']

FA = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
def fa(n): return str(n).translate(FA)

def _slug(m):
    return re.sub(r'\s+', ' ', str(m)).strip()[:60]

def one(s, n=90):
    """پیامِ چندخطی (مثلِ لاگِ playwright) را یک‌خطی و کوتاه می‌کند."""
    return re.sub(r'\s+', ' ', str(s)).strip()[:n]

def _add(level, msg, key):
    RESULTS.append({'section': _CUR[0], 'level': level,
                    'key': key if key else _CUR[0] + '/' + _slug(msg), 'msg': str(msg)})

def ok(m, key=None):   _add('pass', m, key); print("  ✅ " + str(m))
def bad(m, key=None):  _add('fail', m, key); print("  ❌ " + str(m))
def warn(m, key=None): _add('warn', m, key); print("  ⚠️  " + str(m))
def info(m):           print("     · " + str(m))

def fails():  return [r for r in RESULTS if r['level'] == 'fail']
def warns():  return [r for r in RESULTS if r['level'] == 'warn']
def passes(): return [r for r in RESULTS if r['level'] == 'pass']

# ═════════════════════════════ رجیستریِ بخش‌ها
STATIC_SECTIONS, RT_SECTIONS = [], []

def static_section(sid, title, deep=False):
    def deco(fn):
        STATIC_SECTIONS.append({'id': sid, 'title': title, 'fn': fn, 'deep': deep}); return fn
    return deco

def rt_section(sid, title, deep=False):
    def deco(fn):
        RT_SECTIONS.append({'id': sid, 'title': title, 'fn': fn, 'deep': deep}); return fn
    return deco

def run_sections(registry, ctx):
    for s in registry:
        if not ctx.enabled(s['id']):
            continue
        if s['deep'] and not ctx.cfg.get('deep'):
            continue
        print("\n━━━ " + fa(len(TIMINGS) + 1) + ") " + s['title'] + " ━━━")
        _CUR[0] = s['id']
        t0 = time.time()
        try:
            s['fn'](ctx)
        except Exception as ex:
            warn("بخش نیمه‌کاره ماند: " + one(ex, 110), key=s['id'] + '/💥')
        TIMINGS.append({'id': s['id'], 'title': s['title'], 'seconds': round(time.time() - t0, 2)})
        SECTIONS_RUN.append(s['id'])
        _CUR[0] = 'عمومی'

class Ctx:
    """هرچه بخش‌ها لازم دارند؛ هیچ‌چیزِ مخصوصِ یک پروژه‌ی خاص اینجا نیست."""
    def __init__(self, cfg, html, args):
        self.cfg, self.html, self.args = cfg, html, args
        self.only = set(x.strip() for x in (args.only or '').split(',') if x.strip())
        self.skip = set(x.strip() for x in (args.skip or '').split(',') if x.strip()) | set(cfg.get('skip', []))
        self.state = args.state or os.path.join(os.path.dirname(os.path.abspath(html)), '.audit')
        self.shots_dir = '/tmp/audit_shots'
        self.screens, self.errs, self.netfail = [], [], []
        self.guessed, self.cdp, self.timing = False, None, {}
        self.boot_errs, self.boot_res, self.boot_bytes = [], [], 0
        self.reset = lambda: None
    def open_first(self, wait=400):
        """صفحه‌ی اول را باز می‌کند؛ اگر نشد، بخش را نمی‌اندازد."""
        try:
            self.reset()
            if self.screens: self.pg.evaluate(self.screens[0][1])
        except Exception as ex:
            warn("صفحه‌ی اول باز نشد: " + one(ex, 70), key='runtime/first-screen')
        self.pg.wait_for_timeout(wait)
    def enabled(self, sid):
        if sid in self.skip: return False          # --skip همیشه کم می‌کند، حتی داخلِ --only
        return sid in self.only if self.only else True

# ═════════════════════════════ تنظیمات
DEFAULTS = {
    'name': '', 'login': [], 'screens': [], 'reset': '', 'fixture': '', 'schema': '',
    'assets': [], 'themes': [], 'checks': [], 'skip': [], 'allow_missing_ids': [],
    'forbidden': [], 'narrow_width': 320, 'deep': False,
    'touch_min': 44, 'heavy_inline_kb': 120, 'visual_threshold': 2.0,
    'visual_ignore': [], 'perf_budget': {}, 'sql_checks': [], 'db_env': 'DATABASE_URL',
    'forms_submit': False, 'form_values': [], 'sw': '',
}

def load_cfg(path, html):
    d = {}
    if path:
        if os.path.exists(path):
            d = json.load(open(path, encoding='utf-8'))
        else:
            print("  ⚠️  فایلِ تنظیمات پیدا نشد: " + path)
    else:
        # فقط تنظیماتی که کنارِ خودِ پروژه است — نه تنظیماتِ پروژه‌ی دیگر
        guess = os.path.join(os.path.dirname(os.path.abspath(html)), 'audit.config.json')
        if os.path.exists(guess):
            d = json.load(open(guess, encoding='utf-8'))
        else:
            print("  ℹ️  تنظیماتی پیدا نشد — حالتِ خودکار (بررسی‌های عمومی)")
    for k, v in DEFAULTS.items():
        d.setdefault(k, json.loads(json.dumps(v)))
    if not d['name']: d['name'] = os.path.basename(html)
    return d

def near(html, name):
    """فایلِ جانبی: اول کنارِ خودِ پروژه، بعد کنارِ خودِ بازرس. مسیرِ مطلق هم قبول است."""
    if not name: return None
    if os.path.isabs(name):
        return name if os.path.exists(name) else None
    for cand in (os.path.join(os.path.dirname(os.path.abspath(html)), name),
                 os.path.join(HERE, name)):
        if os.path.exists(cand): return cand
    return None

BUILTIN = set("""window document console Math JSON Object Array String Number Boolean Date RegExp Map Set
WeakMap Promise fetch setTimeout setInterval clearTimeout clearInterval alert confirm prompt localStorage
sessionStorage navigator location history parseInt parseFloat isNaN isFinite encodeURIComponent
decodeURIComponent Error TypeError Intl Blob URL File FileReader FormData Image Event CustomEvent
MutationObserver IntersectionObserver requestAnimationFrame cancelAnimationFrame structuredClone crypto
btoa atob Symbol Proxy Reflect globalThis undefined NaN Infinity XMLHttpRequest AbortController
TextEncoder TextDecoder performance screen matchMedia getComputedStyle ResizeObserver Notification
indexedDB caches print open close Function eval require module exports self top parent name status
length AudioContext webkitAudioContext MediaRecorder ReadableStream createImageBitmap AbortSignal
queueMicrotask if for while switch catch return typeof function new this await else delete void
in instanceof throw try do var let const class super yield async of""".split())

DOMWORDS = set('''click change input submit focus blur load error scroll resize keyup keydown keypress
paste ended play pause visibilitychange message open close abort reset select drag drop touchstart
touchend touchmove mouseover mouseout mousedown mouseup contextmenu dblclick wheel toString valueOf
remove replace forEach filter push split join slice trim then catch finally sort map find some every'''.split())

# ═════════════════════════════ جداسازیِ کدِ پروژه از کتابخانه‌ها
def is_vendor(block):
    """کتابخانه‌ی آماده است یا کدِ خودِ پروژه؟ (بدونِ نامِ هیچ کتابخانه‌ی خاصی)"""
    head = block[:600]
    signs = (re.search(r'/\*!', head) or 'sourceMappingURL' in block[-400:]
             or re.search(r'typeof exports\s*==\s*[\'"]object[\'"]', head)
             or re.search(r'define\.amd', head))
    return bool(signs) and len(re.findall(r'getElementById\(', block)) < 3

def split_scripts(src):
    blocks = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', src, flags=re.S | re.I)
    vendor = [b for b in blocks if is_vendor(b)]
    mine = [b for b in blocks if not is_vendor(b)]
    markup = src
    for b in blocks: markup = markup.replace(b, '')
    app = '\n'.join(mine) if mine else (max(blocks, key=len) if blocks else '')
    return blocks, vendor, mine, markup, app

# ═════════════════════════════ بخش‌های ایستا (بدونِ مرورگر)
@static_section('syntax', 'سینتکسِ اسکریپت‌ها')
def _syntax(c):
    if not c.blocks:
        warn("هیچ اسکریپتِ درون‌خطی نیست — بررسی‌های کد رد شد", key='syntax/none'); return
    if not shutil.which('node'):
        warn("node نصب نیست — بررسیِ سینتکس رد شد (نصب: apt install nodejs)", key='syntax/node'); return
    tmp = '/tmp/_audit_js'; os.makedirs(tmp, exist_ok=True)
    broken = []
    for i, b in enumerate(c.blocks):
        p = os.path.join(tmp, '_%d.js' % i)
        open(p, 'w', encoding='utf-8').write(b)
        r = subprocess.run(['node', '--check', p], capture_output=True, text=True)
        if r.returncode != 0:
            tail = (r.stderr.strip().splitlines() or ['?'])[-1][:90]
            broken.append((i, tail))
    if not broken: ok("سینتکسِ هر %s اسکریپت درست است" % fa(len(c.blocks)), key='syntax/all')
    else:
        for i, t in broken: bad("اسکریپتِ %s: %s" % (fa(i), t), key='syntax/%d' % i)

@static_section('ids', 'شناسه‌های تکراری')
def _ids(c):
    dup = sorted({i for i in c.ids if c.ids.count(i) > 1})
    if not dup: ok("هیچ‌کدام از %s شناسه تکراری نیست" % fa(len(c.ids)), key='ids/all')
    else:
        for d in dup: bad("شناسه‌ی تکراری: " + d, key='ids/' + d)

@static_section('dom', 'عنصرهایی که کد صدا می‌زند')
def _dom(c):
    # فقط شناسه‌ی ثابت؛ getElementById('q'+i) شناسه‌ی پویاست و نباید حساب شود
    want = set(re.findall(r"getElementById\(\s*['\"]([A-Za-z][\w-]*)['\"]\s*\)", c.app))
    miss = sorted(w for w in want - c.have if not w.endswith('-'))
    if not miss: ok("هر %s عنصری که کد صدا می‌زند وجود دارد" % fa(len(want)), key='dom/all')
    else:
        for m in miss: bad("عنصرِ گمشده: " + m, key='dom/' + m)

@static_section('handlers', 'دکمه‌ها و توابعشان')
def _handlers(c):
    EVT = (r'on(?:click|change|input|submit|keyup|keydown|keypress|blur|focus|paste|dblclick'
           r'|contextmenu|scroll|load|error|ended)')
    called = {}
    for m in re.finditer(EVT + r'\s*=\s*(["\'])(.*?)\1', c.src, flags=re.S):
        for fm in re.finditer(r'\b([A-Za-z_$][\w$]*)\s*\(', m.group(2)):
            n = fm.group(1)
            if n in BUILTIN or n in c.defined: continue
            if re.search(r'\.\s*' + re.escape(n) + r'\s*\(', m.group(2)): continue
            called[n] = called.get(n, 0) + 1
    if not called: ok("هر دکمه تابعِ خودش را دارد", key='handlers/all')
    else:
        for n, cnt in called.items():
            bad("دکمه‌ای تابعِ «%s» را صدا می‌زند که وجود ندارد (%s بار)" % (n, fa(cnt)), key='handlers/' + n)

@static_section('ghost', 'نامِ تابعِ مرده در متن')
def _ghost(c):
    strnames = set(re.findall(r"['\"]([a-z][A-Za-z]{3,})['\"]\s*[,)]", c.app))
    ghost = sorted(n for n in strnames
                   if n not in c.defined and n not in c.have and n not in BUILTIN and n not in DOMWORDS
                   and re.search(r'(?<![.\w])' + n + r'\s*\(', c.app))
    if not ghost: ok("نامِ تابعِ مرده‌ای به‌صورت متن پاس داده نمی‌شود", key='ghost/all')
    else:
        for g in ghost: bad("نامِ تابعِ حذف‌شده در متن: " + g, key='ghost/' + g)

@static_section('debug', 'کدِ اشکال‌زداییِ جامانده')
def _debug(c):
    left = []
    for pat, label in [(r'\bconsole\.log\(', 'console.log'), (r'\bdebugger\b', 'debugger'),
                       (r'\bTODO\b', 'TODO'), (r'\bFIXME\b', 'FIXME')]:
        n = len(re.findall(pat, c.app))
        if n: left.append("%s×%s" % (label, fa(n)))
    if not left: ok("کدِ اشکال‌زدایی باقی نمانده", key='debug/all')
    else: warn("باقی‌مانده: " + '، '.join(left), key='debug/all')

@static_section('forbidden', 'ردِ چیزهای حذف‌شده')
def _forbidden(c):
    terms = c.cfg['forbidden']
    if not terms:
        ok("فهرستِ «حذف‌شده‌ها» در تنظیمات خالی است — چیزی برای بررسی نبود", key='forbidden/none'); return
    hit = False
    for term in terms:
        n = len(re.findall(r'\b' + re.escape(term) + r'\b', c.src))
        if n:
            hit = True
            bad("ردِ چیزی که باید حذف می‌شد: %s (%s بار)" % (term, fa(n)), key='forbidden/' + term)
    if not hit: ok("هیچ ردی از %s موردِ حذف‌شده نیست" % fa(len(terms)), key='forbidden/all')

@static_section('schema', 'سازگاری با دیتابیس')
def _schema(c):
    if not c.cfg['schema']:
        ok("شِمایی معرفی نشده — این بررسی موضوعی نداشت", key='schema/none'); return
    sch = near(c.html, c.cfg['schema'])
    if not sch:
        warn("فایلِ شِما پیدا نشد: " + c.cfg['schema'], key='schema/missing'); return
    schema = {}
    for ln in open(sch, encoding='utf-8'):
        ln = ln.strip()
        if ln and '|' in ln:
            t, cols = ln.split('|', 1); schema[t] = set(cols.split(','))
    QP = re.compile('[' + chr(34) + chr(39) + chr(96) + ']([a-z_]+)[?]([^' + chr(34) + chr(39) + chr(96) + ']*)')
    prob = []
    for m in QP.finditer(c.app):
        tbl, qs = m.group(1), m.group(2)
        if not re.search(r'select=|order=|limit=|=eq\.|=ilike\.', qs): continue
        if tbl not in schema: prob.append('جدولِ ناشناخته: ' + tbl); continue
        sm = re.search(r'select=([^&]*)', qs)
        if sm:
            sel = sm.group(1)
            for nt, nc in re.findall(r'([a-z_]+)!?\w*\(([^)]*)\)', sel):
                if nt in schema:
                    for col in [x.strip().split(':')[0] for x in nc.split(',') if x.strip()]:
                        if col not in schema[nt]: prob.append('ستونِ تودرتو: %s.%s' % (nt, col))
            flat = re.sub(r'[a-z_]+!?\w*\([^)]*\)', '', sel)
            for col in [x.strip().split(':')[0] for x in flat.split(',') if x.strip()]:
                if col not in ('*', '') and col not in schema[tbl]:
                    prob.append('ستونِ ناموجود: %s.%s' % (tbl, col))
        for fm in re.finditer(r'(?:^|&)([a-z_]+)=(?:eq|neq|gt|gte|lt|lte|like|ilike|is|in|not)\.', qs):
            c2 = fm.group(1)
            if c2 in ('select', 'order', 'limit', 'offset', 'or', 'and'): continue
            if c2 not in schema[tbl]: prob.append('فیلترِ ناموجود: %s.%s' % (tbl, c2))
        om = re.search(r'order=([a-z_]+)', qs)
        if om and om.group(1) not in schema[tbl]:
            prob.append('مرتب‌سازیِ ناموجود: %s.%s' % (tbl, om.group(1)))
    prob = list(dict.fromkeys(prob))
    if not prob: ok("هر پرس‌وجو با %s جدولِ واقعی می‌خوانَد" % fa(len(schema)), key='schema/all')
    else:
        for p in prob: bad(p, key='schema/' + p.split(': ')[-1])

@static_section('bundle', 'حجمِ کدِ شروع')
def _bundle(c):
    if not c.blocks:
        ok("اسکریپتِ درون‌خطی ندارد", key='bundle/none'); return
    limit = c.cfg['heavy_inline_kb'] * 1024
    heavy = [b for b in c.vendor if len(b) > limit]
    total = sum(len(b) for b in c.blocks)
    if not heavy:
        ok("کتابخانه‌ی سنگینی در شروع بار نمی‌شود (کلِ اسکریپت‌ها %s کیلوبایت)" % fa(total // 1024),
           key='bundle/all')
        return
    for b in sorted(heavy, key=len, reverse=True)[:4]:
        tag = re.search(r'/\*!\s*\n?\s*\*?\s*([\w.\- ]{3,40})', b)
        nm = (tag.group(1).strip() if tag else 'کتابخانه‌ی بی‌نام')
        warn("کتابخانه‌ی سنگین در شروع بار می‌شود: %s — %s کیلوبایت (تنبل بارگذاری کن)"
             % (nm, fa(len(b) // 1024)), key='bundle/' + nm[:24])

@static_section('sw', 'فهرستِ کشِ Service Worker')
def _sw(c):
    name = c.cfg['sw']
    if not name:
        m = re.search(r"serviceWorker\s*\.\s*register\(\s*['\"]([^'\"]+)['\"]", c.src)
        if m: name = m.group(1)
    if not name:
        ok("Service Worker ندارد — این بررسی موضوعی نداشت", key='sw/none'); return
    swp = near(c.html, os.path.basename(name.split('?')[0].lstrip('./')))
    if not swp:
        warn("فایلِ Service Worker پیدا نشد: " + name, key='sw/missing'); return
    src = open(swp, encoding='utf-8').read()
    listed = []
    for m in re.finditer(r'addAll\s*\(\s*\[(.*?)\]', src, flags=re.S):
        listed += re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))
    for m in re.finditer(r"cache\.add\(\s*['\"]([^'\"]+)['\"]", src):
        listed.append(m.group(1))
    listed = [x for x in dict.fromkeys(listed) if not re.match(r'^(https?:|data:|//)', x)]
    if not listed:
        ok("فهرستِ کشِ ثابتی ندارد — چیزی برای مقابله نبود", key='sw/nolist'); return
    base = os.path.dirname(os.path.abspath(c.html))
    found, miss = [], []
    for rel in listed:
        p = rel.split('?')[0].lstrip('/')
        if p in ('', '.'): continue
        if p == 'index.html' or os.path.exists(os.path.join(base, p)): found.append(rel)
        else: miss.append(rel)
    if not miss:
        ok("هر %s فایلِ فهرستِ کش کنارِ پروژه هست" % fa(len(listed)), key='sw/all'); return
    # اگر هیچ‌کدام پیدا نشد یعنی ریشه‌ی پروژه جای دیگری است → هشدار، نه ایراد
    lvl = bad if found else warn
    for m in miss:
        lvl("فایلِ فهرستِ کش وجود ندارد (نصبِ SW را می‌شکند): " + m, key='sw/' + m)
    if not found:
        info("هیچ‌کدام از فایل‌های فهرست کنارِ پروژه نبود — شاید ریشه‌ی واقعی جای دیگری است")

@static_section('sql', 'یکپارچگیِ داده (SQL)')
def _sql(c):
    checks = c.cfg['sql_checks']
    if not checks:
        ok("بررسیِ SQL در تنظیمات نیست — این بخش موضوعی نداشت", key='sql/none'); return
    url = os.environ.get(c.cfg['db_env'], '')
    conn, why = None, ''
    if not url:
        why = "متغیرِ %s تنظیم نشده" % c.cfg['db_env']
    else:
        for mod in ('psycopg', 'psycopg2'):
            try:
                conn = __import__(mod).connect(url); break
            except ImportError:
                why = "درایورِ psycopg نصب نیست"; continue
            except Exception as ex:
                why = "اتصال برقرار نشد: " + str(ex)[:60]; break
    if not conn:
        warn("بررسی‌های SQL اجرا نشد (%s) — دستورها را دستی اجرا کن:" % why, key='sql/skipped')
        for ch in checks:
            info('psql "$%s" -c %s' % (c.cfg['db_env'], json.dumps(ch['sql'], ensure_ascii=False)))
            info('   انتظار: %s  ← %s' % (ch.get('expect'), ch['name']))
        return
    cur = conn.cursor()
    for ch in checks:
        try:
            cur.execute(ch['sql'])
            row = cur.fetchone()
            got = row[0] if row and len(row) == 1 else row
            if str(got) == str(ch.get('expect')): ok("%s: %s" % (ch['name'], got), key='sql/' + ch['name'])
            else: bad("%s: %s ≠ انتظار %s" % (ch['name'], got, ch.get('expect')), key='sql/' + ch['name'])
        except Exception as ex:
            bad("%s: 💥 %s" % (ch['name'], str(ex)[:80]), key='sql/' + ch['name'])
    conn.close()

def static_checks(html_path, cfg, ctx):
    src = open(html_path, encoding='utf-8').read()
    blocks, vendor, mine, markup, app = split_scripts(src)
    ids = re.findall(r'\sid\s*=\s*"([\w-]+)"', markup)
    defined = set(re.findall(r'\n\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(', app))
    defined |= set(re.findall(r'(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\()', app))
    have = (set(ids) | set(re.findall(r'id="([\w-]+)"', app)) | set(re.findall(r"id='([\w-]+)'", app))
            | set(re.findall(r"\.id\s*=\s*['\"]([\w-]+)['\"]", app)) | set(cfg['allow_missing_ids']))
    ctx.src, ctx.blocks, ctx.vendor, ctx.mine = src, blocks, vendor, mine
    ctx.markup, ctx.app, ctx.ids, ctx.defined, ctx.have = markup, app, ids, defined, have
    run_sections(STATIC_SECTIONS, ctx)

# ═════════════════════════════ سرورِ محلی
def serve(html_path, extra):
    root = '/tmp/_audit_srv'
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)
    shutil.copy(html_path, os.path.join(root, 'index.html'))
    base = os.path.dirname(os.path.abspath(html_path))
    for f in extra:
        p = os.path.join(base, f)
        if os.path.exists(p): shutil.copy(p, os.path.join(root, os.path.basename(f)))
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    socketserver.TCPServer.allow_reuse_address = True
    srv = None
    for port in range(8931, 8971):
        try:
            srv = socketserver.TCPServer(('127.0.0.1', port), functools.partial(Q, directory=root)); break
        except OSError: continue
    if not srv: raise RuntimeError('پورتِ آزادی برای سرورِ محلی پیدا نشد')
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, 'http://127.0.0.1:%d/index.html' % port

# ═════════════════════════════ بخش‌های زنده (مرورگر)
@rt_section('boot', 'بالا آمدن')
def _boot(c):
    if not c.boot_errs: ok("صفحه بدونِ خطا بالا می‌آید", key='boot/all')
    else:
        for e in c.boot_errs[:6]: bad("خطای شروع: " + one(e, 110), key='boot/' + _slug(e)[:40])

@rt_section('screens', 'باز شدنِ همه‌ی صفحه‌ها')
def _screens(c):
    broke = []
    for nm, js in c.screens:
        n0 = len(c.errs)
        try:
            c.reset(); c.pg.evaluate(js); c.pg.wait_for_timeout(190)
            if len(c.errs) > n0: broke.append((nm, one(c.errs[n0], 80)))
        except Exception as ex: broke.append((nm, one(ex, 80)))
    if not broke:
        ok("هر %s صفحه بدونِ خطا باز شد" % fa(len(c.screens)), key='screens/all')
    elif c.guessed:
        warn("%s تابعِ حدس‌زده خطا داد (شاید بی‌بافت صدا زده شده) — screens را در تنظیمات بنویس"
             % fa(len(broke)), key='screens/guessed')
        for nm, e in broke[:4]: info("%s: %s" % (nm, e[:95]))
    else:
        for nm, e in broke: bad("%s: %s" % (nm, e), key='screens/' + nm)

@rt_section('csp', 'قفلِ امنیتی (CSP)')
def _csp(c):
    v = c.pg.evaluate("()=>window.__CSP||[]")
    if not v: ok("قفلِ امنیتی جلوی هیچ منبعی را نگرفت", key='csp/all')
    else:
        for x in dict.fromkeys(v): bad("قفلِ امنیتی: " + x, key='csp/' + x[:40])

@rt_section('network', 'درخواست‌های شبکه')
def _network(c):
    outside = [f for f in c.netfail if '127.0.0.1' not in f]
    if not outside: ok("همه‌ی درخواست‌ها موفق بودند", key='network/all')
    else:
        for f in list(dict.fromkeys(outside))[:5]: warn("درخواستِ ناموفق: " + f, key='network/' + f[:40])

@rt_section('values', 'مقدارِ خراب در متن')
def _values(c):
    leaks = []
    for nm, js in c.screens:
        try:
            c.reset(); c.pg.evaluate(js); c.pg.wait_for_timeout(150)
            t = c.pg.evaluate("""()=>[...document.querySelectorAll('body *:not(script):not(style):not(template)')]
                  .filter(e=>e.children.length===0).map(e=>e.textContent).join(' | ')""")
            for w in ['NaN', 'undefined', 'Infinity', '[object']:
                if w in t: leaks.append((nm, w))
        except Exception: pass
    if not leaks: ok("هیچ NaN/undefined/Infinity در صفحه‌ها نیست", key='values/all')
    else:
        for nm, w in list(dict.fromkeys(leaks))[:8]:
            bad("مقدارِ خراب: %s → %s" % (nm, w), key='values/%s/%s' % (nm, w))

@rt_section('touch', 'لمس‌پذیریِ دکمه‌ها')
def _touch(c):
    c.open_first(500)
    blocked = c.pg.evaluate("""()=>{ const out=[];
      const bs=[...document.querySelectorAll('button, [role=button], .btn, a[onclick]')];
      for(const b of bs){ const r=b.getBoundingClientRect();
        if(r.width<18||r.height<14) continue;
        if(r.top<0||r.left<0||r.bottom>innerHeight||r.right>innerWidth) continue;
        const cs=getComputedStyle(b); if(cs.visibility==='hidden'||cs.display==='none'||+cs.opacity<0.2) continue;
        const t=document.elementFromPoint(r.left+r.width/2, r.top+r.height/2);
        if(!t) continue;
        if(t!==b && !b.contains(t) && !t.contains(b))
          out.push((b.innerText||b.title||'دکمه').trim().slice(0,20)+' ← روش: '+((t.className&&String(t.className).slice(0,22))||t.tagName));
      } return out.slice(0,6); }""")
    if not blocked: ok("هیچ دکمه‌ای زیرِ چیزِ دیگری گیر نکرده", key='touch/all')
    else:
        for x in blocked: bad("دکمه‌ی مسدود: " + x, key='touch/' + x.split(' ←')[0])

@rt_section('overlay', 'پنجره‌ها (شفافیت)')
def _overlay(c):
    ovs = c.pg.evaluate("()=>document.querySelectorAll('.overlay,[data-overlay],dialog,.modal').length")
    if not ovs:
        warn("پنجره‌ای پیدا نشد — این بررسی رد شد", key='overlay/none'); return
    seethrough = []
    for nm, js in c.screens:
        try:
            c.reset(); c.pg.evaluate(js); c.pg.wait_for_timeout(320)
            r = c.pg.evaluate(r"""()=>{ const o=[...document.querySelectorAll('.overlay,[data-overlay],dialog,.modal')]
                .find(x=>!x.classList.contains('hidden') && x.offsetWidth>200);
              if(!o) return null; const bg=getComputedStyle(o).backgroundColor;
              const p=(bg.match(/[\d.]+/g)||[]).map(Number);
              return {id:o.id||o.className, bg, a:p.length>3?p[3]:1}; }""")
            if r and r['a'] < 0.95: seethrough.append((nm, r['bg']))
        except Exception: pass
    if not seethrough: ok("هر پنجره‌ای که باز شد پس‌زمینه‌ی توپُر داشت", key='overlay/all')
    else:
        for nm, bg in list(dict.fromkeys(seethrough)):
            bad("پنجره‌ی شفاف — پشتش دیده می‌شود: %s (%s)" % (nm, bg), key='overlay/' + nm)

@rt_section('narrow', 'صفحه‌ی باریک')
def _narrow(c):
    w = c.cfg['narrow_width']
    c.pg.set_viewport_size({'width': w, 'height': 800})
    overflow = []
    for nm, js in c.screens:
        try:
            c.reset(); c.pg.evaluate(js); c.pg.wait_for_timeout(190)
            r = c.pg.evaluate("""()=>{ const w=document.documentElement.clientWidth;
              if(document.documentElement.scrollWidth<=w+2) return null;
              const off=[...document.querySelectorAll('body *')].filter(e=>{
                const r=e.getBoundingClientRect(); return r.width>0 && r.right>w+2 && getComputedStyle(e).position!=='fixed'; })
                .map(e=>(e.className&&String(e.className).slice(0,24))||e.tagName);
              return off.slice(0,2); }""")
            if r: overflow.append((nm, r))
        except Exception: pass
    c.pg.set_viewport_size({'width': 412, 'height': 900})
    if not overflow: ok("در صفحه‌ی %s پیکسلی چیزی از کادر بیرون نمی‌زند" % fa(w), key='narrow/all')
    else:
        for nm, r in overflow[:6]: warn("بیرون‌زدگی: %s → %s" % (nm, r), key='narrow/' + nm)

@rt_section('themes', 'تم‌ها')
def _themes(c):
    themes = c.cfg['themes']
    if not themes:
        has = c.pg.evaluate("()=>!!document.querySelector('[data-theme]')"
                            "||/data-theme/.test(document.documentElement.outerHTML.slice(0,4000))")
        if has: themes = [{"name": "تاریک", "js": "document.documentElement.setAttribute('data-theme','dark')"},
                          {"name": "روشن", "js": "document.documentElement.setAttribute('data-theme','light')"}]
    if not themes:
        warn("تمِ دومی پیدا نشد — این بررسی رد شد", key='themes/none'); return
    for th in themes:
        c.pg.evaluate(th['js']); c.pg.wait_for_timeout(250)
        tbroke = []
        for nm, js in c.screens:
            n0 = len(c.errs)
            try:
                c.reset(); c.pg.evaluate(js); c.pg.wait_for_timeout(140)
                if len(c.errs) > n0: tbroke.append((nm, one(c.errs[n0], 60)))
            except Exception as ex: tbroke.append((nm, one(ex, 60)))
        if not tbroke: ok("همه‌ی صفحه‌ها در تمِ %s هم سالم‌اند" % th['name'], key='themes/' + th['name'])
        elif c.guessed:
            warn("تمِ %s: %s تابعِ حدس‌زده خطا داد" % (th['name'], fa(len(tbroke))), key='themes/' + th['name'])
        else:
            for nm, e in tbroke:
                bad("تمِ %s — %s: %s" % (th['name'], nm, e), key='themes/%s/%s' % (th['name'], nm))

@rt_section('checks', 'بررسی‌های ویژه‌ی پروژه')
def _checks(c):
    if not c.cfg['checks']:
        ok("بررسیِ ویژه‌ای در تنظیمات نیست", key='checks/none'); return
    for ch in c.cfg['checks']:
        k = 'checks/' + ch['name']
        try:
            if ch.get('before'):
                c.reset(); c.pg.evaluate(ch['before']); c.pg.wait_for_timeout(ch.get('wait', 400))
            got, exp = c.pg.evaluate(ch['js']), ch['expect']
            if str(got) == str(exp): ok("%s: %s" % (ch['name'], got), key=k)
            else: bad("%s: %s ≠ انتظار %s" % (ch['name'], got, exp), key=k)
        except Exception as ex:
            bad("%s: 💥 %s" % (ch['name'], one(ex, 80)), key=k)

@rt_section('a11y', 'دسترس‌پذیری و لمس روی موبایل')
def _a11y(c):
    c.open_first(300)
    r = c.pg.evaluate("""(min)=>{
      const vis=e=>{const b=e.getBoundingClientRect(); if(!b.width||!b.height) return false;
        const s=getComputedStyle(e); return s.visibility!=='hidden'&&s.display!=='none'&&+s.opacity>0.05;};
      const nm=e=>e.getAttribute('aria-label')||e.getAttribute('aria-labelledby')||e.getAttribute('title')
        ||(e.id&&document.querySelector('label[for="'+CSS.escape(e.id)+'"]'))||e.closest('label');
      const small=[], noname=[], onlyph=[], noalt=[];
      for(const e of document.querySelectorAll('button,[role=button],a[href],a[onclick],input,select,textarea')){
        if(!vis(e)||e.type==='hidden') continue;
        const b=e.getBoundingClientRect();
        if(b.width<min||b.height<min) small.push((((e.innerText||e.value||e.name||e.id||e.tagName)+'').trim()||'؟').slice(0,18)
          +' ('+Math.round(b.width)+'×'+Math.round(b.height)+')');
      }
      for(const e of document.querySelectorAll('input,select,textarea')){
        if(!vis(e)||['hidden','submit','button','image','reset'].includes(e.type)) continue;
        if(nm(e)) continue;
        (e.placeholder?onlyph:noname).push((e.id||e.name||e.type||e.tagName)+'');
      }
      for(const e of document.querySelectorAll('img')){
        if(!vis(e)) continue;
        if(!e.hasAttribute('alt')) noalt.push((e.getAttribute('src')||'img').slice(-28));
      }
      const u=a=>[...new Set(a)];
      return {small:u(small), noname:u(noname), onlyph:u(onlyph), noalt:u(noalt)}; }""", c.cfg['touch_min'])
    mn = fa(c.cfg['touch_min'])
    if not r['small']: ok("همه‌ی هدف‌های لمس از %s×%s بزرگ‌ترند" % (mn, mn), key='a11y/touch')
    else: warn("هدفِ لمسِ کوچک‌تر از %s پیکسل (%s مورد): %s"
               % (mn, fa(len(r['small'])), '، '.join(r['small'][:5])), key='a11y/touch')
    if not r['noname'] and not r['onlyph']:
        ok("هر ورودی برچسبِ قابلِ خواندن دارد", key='a11y/label')
    else:
        if r['noname']: warn("ورودیِ بدونِ label/aria-label (%s مورد): %s"
                             % (fa(len(r['noname'])), '، '.join(r['noname'][:5])), key='a11y/label')
        if r['onlyph']: warn("ورودی فقط placeholder دارد و برچسبِ واقعی ندارد (%s مورد): %s"
                             % (fa(len(r['onlyph'])), '، '.join(r['onlyph'][:5])), key='a11y/placeholder')
    if not r['noalt']: ok("هر تصویری alt دارد", key='a11y/alt')
    else: warn("تصویرِ بدونِ alt (%s مورد): %s" % (fa(len(r['noalt'])), '، '.join(r['noalt'][:4])), key='a11y/alt')

    # گیر افتادنِ فوکوس داخلِ پنجره‌ی باز
    escaped, tried = [], 0
    OV = '.overlay,[data-overlay],dialog,.modal'
    for nm, js in c.screens:
        if tried >= 6: break
        try:
            c.reset(); c.pg.evaluate(js); c.pg.wait_for_timeout(260)
            started = c.pg.evaluate("""(sel)=>{ const o=[...document.querySelectorAll(sel)]
                .find(x=>!x.classList.contains('hidden') && x.offsetWidth>200 && getComputedStyle(x).display!=='none');
              if(!o) return false;
              const f=o.querySelector('button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])');
              if(!f) return false; f.focus(); return document.activeElement!==document.body; }""", OV)
            if not started: continue
            tried += 1
            out = False
            for _ in range(12):
                c.pg.keyboard.press('Tab')
                if c.pg.evaluate("""(sel)=>{ const a=document.activeElement;
                    if(!a||a===document.body||a===document.documentElement) return false;
                    return !a.closest(sel); }""", OV):
                    out = True; break
            if out: escaped.append(nm)
        except Exception: pass
    if not tried: warn("پنجره‌ای برای آزمونِ فوکوس باز نشد — این بررسی رد شد", key='a11y/focus-none')
    elif not escaped: ok("فوکوس در %s پنجره داخلِ خودش می‌مانَد" % fa(tried), key='a11y/focus')
    else:
        for nm in escaped: warn("فوکوس با Tab از پنجره بیرون می‌پرد: " + nm, key='a11y/focus/' + nm)

@rt_section('perf', 'کیفیتِ بارگذاری')
def _perf(c):
    budget = c.cfg['perf_budget']
    kb = c.boot_bytes // 1024
    lim = budget.get('weight_kb')
    msg = "حجمِ صفحه در شروع: %s کیلوبایت" % fa(kb)
    if lim and kb > lim: warn(msg + " — بیشتر از بودجه‌ی %s" % fa(lim), key='perf/weight')
    else: ok(msg, key='perf/weight')
    for u, n in sorted(c.boot_res, key=lambda x: -x[1])[:3]:
        if n: info("%s کیلوبایت ← %s" % (fa(n // 1024), u[-60:]))
    for label, field, bkey in [("اولین ترسیمِ محتوا (FCP)", 'fcp', 'fcp_ms'),
                               ("تعاملی‌شدنِ DOM", 'dom', 'dom_interactive_ms'),
                               ("پایانِ بارگذاری", 'load', 'load_ms')]:
        v = (c.timing or {}).get(field)
        if not v: continue
        lim = budget.get(bkey)
        m = "%s: %s میلی‌ثانیه" % (label, fa(int(v)))
        if lim and v > lim: warn(m + " — بیشتر از بودجه‌ی %s" % fa(lim), key='perf/' + field)
        else: ok(m, key='perf/' + field)

@rt_section('coverage', 'کدِ بارشده ولی بلااستفاده', deep=True)
def _coverage(c):
    if not c.cdp:
        warn("دسترسیِ CDP نبود — این بررسی رد شد", key='coverage/none'); return
    try:
        res = c.cdp.send('Profiler.takePreciseCoverage')
    except Exception as ex:
        warn("پوششِ کد خوانده نشد: " + str(ex)[:70], key='coverage/none'); return
    idle = []
    for entry in res.get('result', []):
        # بازه‌ها تودرتوان: بیرونی‌ترین اول، بعد درونی‌ها رویش نوشته می‌شوند.
        # (فقط نگاه کردن به بازه‌ی بیرونی غلط است — پوسته‌ی هر کتابخانه اجرا می‌شود
        #  ولی درونش دست‌نخورده می‌مانَد.)
        rngs = [r for f in entry.get('functions', []) for r in (f.get('ranges') or [])]
        if not rngs: continue
        total = max(r['endOffset'] for r in rngs)
        if total <= 100 * 1024: continue
        cov = bytearray(total)
        for r in sorted(rngs, key=lambda r: (r['startOffset'], -r['endOffset'])):
            cov[r['startOffset']:r['endOffset']] = bytes([1 if r.get('count', 0) > 0 else 0]) \
                                                   * (r['endOffset'] - r['startOffset'])
        used = sum(cov)
        # کتابخانه‌ای که بار می‌شود و «خودش را می‌سازد» ولی کارش را نمی‌کنی،
        # حدودِ نیمی از بایت‌هایش اجرا می‌شود؛ پس معیار، بایتِ هدررفته است نه فقط نسبت.
        if total - used > 60 * 1024 and used / total < 0.6:
            idle.append((entry.get('url') or 'inline', total, used))
    if not idle: ok("کدِ سنگینِ بلااستفاده‌ای در شروع بار نشد", key='coverage/all')
    else:
        idle.sort(key=lambda x: -(x[1] - x[2]))
        for i, (u, tot, used) in enumerate(idle[:4]):
            warn("%s کیلوبایت بار شد ولی %s کیلوبایتش هرگز اجرا نشد (%s٪ استفاده) ← %s"
                 % (fa(tot // 1024), fa((tot - used) // 1024), fa(int(100 * used / tot)), u[-46:]),
                 key='coverage/%d/%s' % (i, u[-30:]))

@rt_section('shots', 'عکس‌برداری')
def _shots(c):
    n, rects = 0, {}
    for nm, js in c.screens[:14]:
        try:
            c.reset(); c.pg.evaluate(js); c.pg.wait_for_timeout(420)
            safe = re.sub(r'[^\w؀-ۿ]+', '_', nm)[:24]
            fn = "%02d_%s.png" % (n, safe)
            if c.cfg['visual_ignore']:
                rects[fn] = c.pg.evaluate("""(sels)=>{const out=[];
                  for(const s of sels){ let els=[]; try{els=[...document.querySelectorAll(s)];}catch(e){}
                    for(const e of els){const r=e.getBoundingClientRect();
                      if(r.width>0&&r.height>0) out.push([Math.max(0,Math.floor(r.left)),Math.max(0,Math.floor(r.top)),
                        Math.ceil(r.right),Math.ceil(r.bottom)]);}}
                  return out;}""", c.cfg['visual_ignore'])
            c.pg.screenshot(path=os.path.join(c.shots_dir, fn)); n += 1
        except Exception: pass
    if rects:
        json.dump(rects, open(os.path.join(c.shots_dir, '_rects.json'), 'w'), ensure_ascii=False)
    c.shot_count = n
    ok("%s عکس در %s ذخیره شد — حتماً چندتا را با چشم ببین" % (fa(n), c.shots_dir), key='shots/all')

@rt_section('visual', 'مقایسه‌ی تصویری با اجرای قبلی')
def _visual(c):
    try:
        from PIL import Image, ImageChops, ImageDraw
    except ImportError:
        warn("Pillow نصب نیست — مقایسه‌ی تصویری رد شد (نصب: pip install pillow)", key='visual/none'); return
    base, cur = os.path.join(c.state, 'shots'), c.shots_dir
    if not os.path.isdir(base) or not [f for f in os.listdir(base) if f.endswith('.png')]:
        warn("عکسِ مرجعی از اجرای قبلی نیست — همین اجرا مرجع شد", key='visual/none'); return
    def rects_of(d):
        p = os.path.join(d, '_rects.json')
        return json.load(open(p)) if os.path.exists(p) else {}
    old_r, new_r = rects_of(base), rects_of(cur)

    def masked(path, rects):
        im = Image.open(path).convert('RGB')
        if rects:
            d = ImageDraw.Draw(im)
            for x1, y1, x2, y2 in rects: d.rectangle([x1, y1, x2, y2], fill=(0, 0, 0))
        return im

    thr = float(c.cfg['visual_threshold'])
    changed, gone = [], []
    for f in sorted(x for x in os.listdir(base) if x.endswith('.png')):
        p_new = os.path.join(cur, f)
        if not os.path.exists(p_new):
            gone.append(f); continue
        rects = (old_r.get(f) or []) + (new_r.get(f) or [])
        a, b = masked(os.path.join(base, f), rects), masked(p_new, rects)
        if a.size != b.size:
            changed.append((f, -1.0)); continue
        diff = ImageChops.difference(a, b).convert('L').point(lambda v: 255 if v > 30 else 0)
        pct = 100.0 * sum(diff.histogram()[255:]) / (a.size[0] * a.size[1])
        if pct > thr: changed.append((f, pct))
    if not changed and not gone:
        ok("هیچ صفحه‌ای بیش از %s٪ با اجرای قبلی فرق نکرد" % thr, key='visual/all')
    for f, pct in changed:
        label = "اندازه‌ی صفحه عوض شد" if pct < 0 else "%s٪ تغییر" % fa(round(pct, 1))
        warn("تغییرِ تصویری: %s — %s" % (f, label), key='visual/' + f)
    for f in gone:
        warn("عکسِ این صفحه دیگر گرفته نشد: " + f, key='visual/gone/' + f)

@rt_section('forms', 'سلامتِ فرم‌ها (مقادیرِ مرزی)')
def _forms(c):
    values = c.cfg['form_values'] or ['', 'ا' * 300, '-1', '0', '<script>alert(1)</script>',
                                      '۱۲۳۴۵۶۷۸۹۰', 'سلام «تست» ۱۲۳ / test']
    FILL = """(v)=>{ let n=0;
      const els=[...document.querySelectorAll('input,textarea')].filter(e=>{
        const r=e.getBoundingClientRect(); if(!r.width||!r.height) return false;
        const s=getComputedStyle(e); if(s.visibility==='hidden'||s.display==='none') return false;
        return !['hidden','file','submit','button','image','reset','checkbox','radio'].includes(e.type); }).slice(0,25);
      for(const e of els){
        const proto = e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
        const set = Object.getOwnPropertyDescriptor(proto,'value').set;
        try{ set.call(e, v); }catch(err){ continue; }
        for(const t of ['input','change','blur']) e.dispatchEvent(new Event(t,{bubbles:true}));
        n++; }
      return n; }"""
    TEXT = """()=>[...document.querySelectorAll('body *:not(script):not(style):not(template)')]
          .filter(e=>e.children.length===0).map(e=>e.textContent).join(' | ')"""
    crashed, leaked, touched = [], [], 0
    for nm, js in c.screens:
        try:
            c.reset(); c.pg.evaluate(js); c.pg.wait_for_timeout(200)
        except Exception:
            continue
        for v in values:
            n0 = len(c.errs)
            try:
                touched += c.pg.evaluate(FILL, v)
                c.pg.wait_for_timeout(60)
            except Exception as ex:
                crashed.append((nm, v, one(ex, 60))); continue
            if len(c.errs) > n0: crashed.append((nm, v, one(c.errs[n0], 70)))
            try:
                t = c.pg.evaluate(TEXT)
            except Exception:
                continue
            for w in ['NaN', 'undefined', 'Infinity']:
                if w in t: leaked.append((nm, v, w))
        if c.cfg['forms_submit']:
            try:
                c.pg.evaluate("""()=>{ const f=[...document.querySelectorAll('form')].find(x=>x.offsetWidth>0);
                  if(f) f.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})); }""")
                c.pg.wait_for_timeout(250)
            except Exception: pass
    if not touched:
        warn("ورودیِ قابلِ آزمونی پیدا نشد — این بررسی رد شد", key='forms/none'); return
    shown = lambda v: (v[:14] + '…') if len(v) > 15 else (v or 'خالی')
    if not crashed:
        ok("%s ورودی با %s مقدارِ مرزی پر شد و صفحه خطا نداد" % (fa(touched), fa(len(values))), key='forms/crash')
    else:
        lvl = warn if c.guessed else bad
        for nm, v, e in list(dict.fromkeys(crashed))[:6]:
            lvl("خطای فرم — %s با «%s»: %s" % (nm, shown(v), e), key='forms/%s/%s' % (nm, shown(v)))
    if not leaked: ok("با مقادیرِ مرزی هم NaN/undefined در صفحه نیامد", key='forms/leak')
    else:
        for nm, v, w in list(dict.fromkeys(leaked))[:6]:
            warn("مقدارِ خراب بعد از ورودیِ «%s» در %s → %s" % (shown(v), nm, w),
                 key='forms/leak/%s/%s' % (nm, w))

# ═════════════════════════════ اجرای زنده
def runtime_checks(url, cfg, html_path, ctx):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        warn("playwright نصب نیست — همه‌ی بررسی‌های زنده رد شد "
             "(نصب: pip install playwright && playwright install chromium)", key='runtime/none')
        return

    fixture = ''
    if cfg['fixture']:
        p = near(html_path, cfg['fixture'])   # نامِ صریح در تنظیمات لازم است
        if p: fixture = open(p, encoding='utf-8').read()
        else: warn("فایلِ شبیه‌ساز پیدا نشد: " + cfg['fixture'], key='runtime/fixture')

    shutil.rmtree(ctx.shots_dir, ignore_errors=True)
    os.makedirs(ctx.shots_dir, exist_ok=True)

    try:
        pw = sync_playwright().start()
    except Exception as ex:
        warn("playwright بالا نیامد: " + one(ex, 90), key='runtime/none'); return
    # اگر مرورگرِ همراهِ playwright نبود، مسیرِ دستی از متغیرِ AUDIT_CHROMIUM
    launch = {}
    if os.environ.get('AUDIT_CHROMIUM'):
        launch['executable_path'] = os.environ['AUDIT_CHROMIUM']
    try:
        br = pw.chromium.launch(**launch)
    except Exception as ex:
        warn("کرومیوم اجرا نشد — %s (نصب: playwright install chromium، "
             "یا مسیرِ دستی در متغیرِ AUDIT_CHROMIUM)" % one(ex, 80), key='runtime/none')
        pw.stop(); return

    try:
        pg = br.new_page(viewport={'width': 412, 'height': 900})
        ctx.pg = pg
        res_seen = []
        def on_response(r):
            if r.status >= 400: ctx.netfail.append("%d %s" % (r.status, r.url[:80]))
            try: res_seen.append((r.url, int(r.headers.get('content-length') or 0)))
            except Exception: pass
        pg.on('pageerror', lambda e: ctx.errs.append(str(e)))
        pg.on('response', on_response)
        pg.on('dialog', lambda d: d.accept())
        if fixture: pg.add_init_script(fixture)
        pg.add_init_script("document.addEventListener('securitypolicyviolation',"
                           "e=>{(window.__CSP=window.__CSP||[]).push(e.violatedDirective+' → '+e.blockedURI.slice(0,60))});")

        if cfg.get('deep'):
            try:
                ctx.cdp = pg.context.new_cdp_session(pg)
                ctx.cdp.send('Profiler.enable')
                ctx.cdp.send('Profiler.startPreciseCoverage', {'callCount': False, 'detailed': True})
            except Exception:
                ctx.cdp = None

        pg.goto(url); pg.wait_for_timeout(600)
        ctx.boot_errs = list(ctx.errs)
        ctx.boot_res = list(res_seen)
        ctx.boot_bytes = sum(n for _, n in ctx.boot_res)
        try:
            ctx.timing = pg.evaluate("""()=>{ const n=performance.getEntriesByType('navigation')[0]||{};
              const p=performance.getEntriesByName('first-contentful-paint')[0];
              return {fcp:p?p.startTime:0, dom:n.domInteractive||0, load:n.loadEventEnd||0}; }""")
        except Exception:
            ctx.timing = {}

        for step in cfg['login']:
            try:
                to = step.get('timeout', 5000)
                if 'fill' in step: pg.fill(step['fill'], step.get('value', ''), timeout=to)
                elif 'click' in step: pg.click(step['click'], timeout=to)
                elif 'js' in step: pg.evaluate(step['js'])
                pg.wait_for_timeout(step.get('wait', 250))
            except Exception as ex:
                warn("مرحله‌ی ورود رد شد: " + one(ex, 70), key='runtime/login')
        if cfg['login']: pg.wait_for_timeout(900)

        screens = [tuple(s) for s in cfg['screens']]
        ctx.guessed = not screens
        if not screens:
            src = open(html_path, encoding='utf-8').read()
            cand = sorted({m.group(1) for m in re.finditer(r'onclick="([a-zA-Z_$][\w$]*\(\s*\))"', src)})
            screens = [(x[:-2], x) for x in cand[:25]]
            if screens:
                warn("فهرستِ صفحه‌ها در تنظیمات نبود — %s تا خودکار پیدا شد" % fa(len(screens)),
                     key='runtime/screens-guessed')
        ctx.screens = screens or [('صفحه‌ی اصلی', '1')]
        ctx.reset = (lambda: pg.evaluate(cfg['reset'])) if cfg['reset'] else (lambda: None)

        run_sections(RT_SECTIONS, ctx)
    finally:
        try: br.close()
        except Exception: pass
        try: pw.stop()
        except Exception: pass

# ═════════════════════════════ رگرسیون و ذخیره‌ی وضعیت
def compare_with_last(ctx):
    print("\n━━━ مقایسه با اجرای قبلی ━━━")
    path = os.path.join(ctx.state, 'last.json')
    if not os.path.exists(path):
        print("  ℹ️  اجرای قبلی‌ای ثبت نشده — همین اجرا مبنا شد")
        return {'broke': [], 'fixed': []}
    try:
        old = json.load(open(path, encoding='utf-8'))
    except Exception as ex:
        print("  ⚠️  پرونده‌ی اجرای قبلی خوانده نشد: " + str(ex)[:60])
        return {'broke': [], 'fixed': []}
    ran = set(SECTIONS_RUN) & set(old.get('sections_run', []))
    old_lv = {r['key']: r['level'] for r in old.get('results', []) if r['section'] in ran}
    new_lv = {r['key']: r['level'] for r in RESULTS if r['section'] in ran}
    broke, fixed = [], []
    for k, lv in new_lv.items():
        if lv == 'fail' and old_lv.get(k, 'pass') != 'fail': broke.append(k)
        elif lv == 'warn' and old_lv.get(k, 'warn') == 'pass': broke.append(k)
    for k, lv in old_lv.items():
        if lv in ('fail', 'warn') and new_lv.get(k, 'pass') == 'pass': fixed.append(k)
    if not broke and not fixed:
        print("  ✅ نسبت به اجرای قبلی نه چیزی خراب شد نه چیزی درست")
    for k in sorted(broke)[:12]:
        msg = next((r['msg'] for r in RESULTS if r['key'] == k), k)
        print("  🔻 تازه خراب شد: " + msg[:100])
    for k in sorted(fixed)[:12]:
        msg = next((r['msg'] for r in old.get('results', []) if r['key'] == k), k)
        print("  🔺 درست شد: " + msg[:100])
    return {'broke': sorted(broke), 'fixed': sorted(fixed)}

def save_state(ctx):
    os.makedirs(ctx.state, exist_ok=True)
    json.dump({'results': RESULTS, 'sections_run': SECTIONS_RUN, 'at': time.time()},
              open(os.path.join(ctx.state, 'last.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    src = ctx.shots_dir
    if os.path.isdir(src) and os.listdir(src) and 'shots' in SECTIONS_RUN:
        dst = os.path.join(ctx.state, 'shots')
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)

# ═════════════════════════════ main
def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('html', nargs='?')
    ap.add_argument('-c', '--config', default=None)
    ap.add_argument('--json', dest='json_out', default=None, help='گزارشِ ماشین‌خوان برای CI')
    ap.add_argument('--only', default=None, help='فقط این بخش‌ها (با کاما)')
    ap.add_argument('--skip', default=None, help='این بخش‌ها اجرا نشوند (با کاما)')
    ap.add_argument('--state', default=None, help='پوشه‌ی وضعیت (پیش‌فرض: .audit کنارِ پروژه)')
    ap.add_argument('--no-save', action='store_true', help='وضعیت را ذخیره نکن')
    ap.add_argument('--deep', action='store_true', help='بررسی‌های سنگین هم اجرا شود')
    ap.add_argument('--quiet', action='store_true', help='فقط خلاصه')
    ap.add_argument('--list', action='store_true', help='فهرستِ بخش‌ها')
    a = ap.parse_args()

    if a.list:
        print("بخش‌های ایستا:  " + ', '.join(s['id'] for s in STATIC_SECTIONS))
        print("بخش‌های زنده:  " + ', '.join(s['id'] + ('*' if s['deep'] else '') for s in RT_SECTIONS))
        print("(* = فقط با --deep)")
        return 0
    if not a.html: ap.error('مسیرِ index.html لازم است')
    if not os.path.exists(a.html):
        print("  ❌ فایل پیدا نشد: " + a.html); return 1

    if a.quiet:
        globals()['ok'] = lambda m, key=None: _add('pass', m, key)

    t_start = time.time()
    cfg = load_cfg(a.config, a.html)
    if a.deep: cfg['deep'] = True
    ctx = Ctx(cfg, a.html, a)

    print("\n" + "═" * 52)
    print("  بازرسِ عمومی — پروژه: " + cfg['name'])
    print("═" * 52)

    static_checks(a.html, cfg, ctx)

    if any(ctx.enabled(s['id']) and (not s['deep'] or cfg.get('deep')) for s in RT_SECTIONS):
        srv, url = serve(a.html, cfg['assets'])
        try: runtime_checks(url, cfg, a.html, ctx)
        finally: srv.shutdown()

    reg = compare_with_last(ctx)
    if not a.no_save: save_state(ctx)

    print("\n━━━ زمان‌بندی ━━━")
    for t in sorted(TIMINGS, key=lambda x: -x['seconds'])[:8]:
        print("  %6.2f ثانیه  %s" % (t['seconds'], t['title']))
    total = round(time.time() - t_start, 2)
    print("  ─────  جمع: %.2f ثانیه" % total)

    print("\n" + "═" * 52)
    print("  %s بررسی پاس شد" % fa(len(passes())))
    if warns():
        print("  ⚠️  %s هشدارِ غیربحرانی" % fa(len(warns())))
        for w in warns(): print("     ⚠️  " + w['msg'][:110])
    if fails():
        print("  ❌ %s ایراد — تحویل نده:" % fa(len(fails())))
        for f in fails(): print("     • " + f['msg'][:110])
    else:
        print("  ✅ آماده‌ی تحویل")

    code = 1 if fails() else 0
    if a.json_out:
        out = {'project': cfg['name'], 'html': os.path.abspath(a.html),
               'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'duration_s': total,
               'counts': {'pass': len(passes()), 'warn': len(warns()), 'fail': len(fails())},
               'sections_run': SECTIONS_RUN, 'timings': TIMINGS,
               'results': RESULTS, 'regression': reg, 'exit': code}
        d = os.path.dirname(os.path.abspath(a.json_out))
        if d: os.makedirs(d, exist_ok=True)
        json.dump(out, open(a.json_out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print("  📄 گزارشِ ماشین‌خوان: " + a.json_out)
    return code

if __name__ == '__main__':
    sys.exit(main())
