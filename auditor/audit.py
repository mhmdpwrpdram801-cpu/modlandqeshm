#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بازرسِ عمومیِ اپلیکیشن‌های وب — یک موتور برای همه‌ی پروژه‌ها.

  python3 audit.py <index.html>                 # بدونِ تنظیمات هم کار می‌کند
  python3 audit.py <index.html> -c config.json  # با تنظیماتِ پروژه

خروجی: کدِ ۰ یعنی آماده‌ی تحویل، ۱ یعنی ایراد دارد.
"""
import sys, os, re, json, argparse, subprocess, threading, functools
import http.server, socketserver

HERE = os.path.dirname(os.path.abspath(__file__))
FAILS, WARNS, PASSES = [], [], []

def ok(m):   PASSES.append(m); print("  ✅ " + m)
def bad(m):  FAILS.append(m);  print("  ❌ " + m)
def warn(m): WARNS.append(m);  print("  ⚠️  " + m)
def head(t): print("\n━━━ " + t + " ━━━")

# ───────────────────────────── تنظیمات
def load_cfg(path, html):
    d = {}
    if path and os.path.exists(path):
        d = json.load(open(path, encoding='utf-8'))
    elif not path:
        # فقط تنظیماتی که کنارِ خودِ پروژه است — نه تنظیماتِ پروژه‌ی دیگر
        guess = os.path.join(os.path.dirname(os.path.abspath(html)), 'audit.config.json')
        if os.path.exists(guess):
            d = json.load(open(guess, encoding='utf-8'))
        else:
            print("  ℹ️  تنظیماتی پیدا نشد — حالتِ خودکار (بررسی‌های عمومی)")
    d.setdefault('name', os.path.basename(html))
    d.setdefault('login', [])
    d.setdefault('login_done', '')
    d.setdefault('screens', [])
    d.setdefault('reset', '')
    d.setdefault('fixture', '')
    d.setdefault('schema', '')
    d.setdefault('assets', [])
    d.setdefault('themes', [])
    d.setdefault('checks', [])
    d.setdefault('skip', [])
    d.setdefault('allow_missing_ids', [])
    d.setdefault('allow_hscroll', [])
    d.setdefault('narrow_width', 320)
    return d

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

# ───────────────────────────── ایستا (بدونِ مرورگر)
def static_checks(html_path, cfg):
    src = open(html_path, encoding='utf-8').read()
    blocks = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', src, flags=re.S | re.I)
    markup = src
    for b in blocks: markup = markup.replace(b, '')
    app = max(blocks, key=len) if blocks else ''

    head("۱) ساختارِ کد")
    if not blocks:
        warn("هیچ اسکریپتِ درون‌خطی نیست — بررسی‌های کد رد شد")
    bad_syntax = []
    for i, b in enumerate(blocks):
        p = f'/tmp/_audit_{i}.js'
        open(p, 'w', encoding='utf-8').write(b)
        r = subprocess.run(['node', '--check', p], capture_output=True, text=True)
        if r.returncode != 0:
            bad_syntax.append(f"اسکریپتِ {i}: {r.stderr.strip().splitlines()[-1][:90]}")
    ok(f"سینتکسِ هر {len(blocks)} اسکریپت درست است") if not bad_syntax else [bad(x) for x in bad_syntax]


    # اعتبارِ ساختارِ HTML — تگِ بسته‌نشده باعث می‌شود عناصر جای اشتباه لانه کنند
    _h = src
    for _b in re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', _h, flags=re.S | re.I): _h = _h.replace(_b, '')
    for _b in re.findall(r'<style[^>]*>(.*?)</style>', _h, flags=re.S | re.I): _h = _h.replace(_b, '')
    VOID = {'br','hr','img','input','meta','link','source','track','area','base','col','embed','param','wbr','path','svg','use','circle','rect','line','polygon','polyline','ellipse'}
    _stack, _bad = [], []
    for m in re.finditer(r'<(/?)([a-zA-Z][\w-]*)([^>]*?)(/?)>', _h):
        cl, tag, slf = m.group(1), m.group(2).lower(), m.group(4)
        if tag in VOID or slf == '/': continue
        if not cl: _stack.append(tag)
        else:
            if _stack and _stack[-1] == tag: _stack.pop()
            else:
                hit = False
                for k in range(len(_stack) - 1, -1, -1):
                    if _stack[k] == tag:
                        _bad.append('تگِ بسته‌نشده: ' + '، '.join(_stack[k + 1:][:4])); _stack = _stack[:k]; hit = True; break
                if not hit: _bad.append('بستنِ اضافه: ' + tag)
    if _stack: _bad.append('در پایان باز مانده: ' + '، '.join(_stack[:4]))
    ok("ساختارِ HTML سالم است (هر تگ درست بسته شده)") if not _bad else [bad(x) for x in _bad[:6]]

    ids = re.findall(r'\sid\s*=\s*"([\w-]+)"', markup)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    ok(f"هیچ‌کدام از {len(ids)} شناسه تکراری نیست") if not dup else bad("شناسه‌ی تکراری: " + ', '.join(dup))

    want = set(re.findall(r"getElementById\(\s*['\"]([A-Za-z][\w-]*)['\"]", app))
    have = (set(ids) | set(re.findall(r'id="([\w-]+)"', app)) | set(re.findall(r"id='([\w-]+)'", app))
            | set(re.findall(r"\.id\s*=\s*['\"]([\w-]+)['\"]", app)) | set(cfg['allow_missing_ids']))
    miss = sorted(w for w in want - have if not w.endswith('-'))
    ok(f"هر {len(want)} عنصری که کد صدا می‌زند وجود دارد") if not miss else bad("عنصرِ گمشده: " + ', '.join(miss))

    defined = set(re.findall(r'\n\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(', app))
    defined |= set(re.findall(r'(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\()', app))
    EVT = r'on(?:click|change|input|submit|keyup|keydown|keypress|blur|focus|paste|dblclick|contextmenu|scroll|load|error|ended)'
    called = {}
    for m in re.finditer(EVT + r'\s*=\s*(["\'])(.*?)\1', src, flags=re.S):
        for fm in re.finditer(r'\b([A-Za-z_$][\w$]*)\s*\(', m.group(2)):
            n = fm.group(1)
            if n in BUILTIN or n in defined: continue
            if re.search(r'\.\s*' + re.escape(n) + r'\s*\(', m.group(2)): continue
            called[n] = called.get(n, 0) + 1
    ok(f"هر {sum(called.values()) + 1 if called else 'یک'} دکمه تابعِ خودش را دارد") if not called \
        else [bad(f"دکمه‌ای تابعِ «{n}» را صدا می‌زند که وجود ندارد ({c} بار)") for n, c in called.items()]

    # نامِ تابع که به‌صورت متن پاس داده می‌شود ولی تعریف نشده (باگِ خاموش)
    DOMWORDS = set('''click change input submit focus blur load error scroll resize keyup keydown keypress
    paste ended play pause visibilitychange message open close abort reset select drag drop touchstart
    touchend touchmove mouseover mouseout mousedown mouseup contextmenu dblclick wheel toString valueOf
    remove replace forEach filter push split join slice trim then catch finally sort map find some every'''.split())
    strnames = set(re.findall(r"['\"]([a-z][A-Za-z]{3,})['\"]\s*[,)]", app))
    ghost = sorted(n for n in strnames
                   if n not in defined and n not in have and n not in BUILTIN and n not in DOMWORDS
                   and re.search(r'(?<![.\w])' + n + r'\s*\(', app))
    ok("نامِ تابعِ مرده‌ای به‌صورت متن پاس داده نمی‌شود") if not ghost \
        else [bad("نامِ تابعِ حذف‌شده در متن: " + g) for g in ghost]

    leftovers = []
    for pat, label in [(r'\bconsole\.log\(', 'console.log'), (r'\bdebugger\b', 'debugger'),
                       (r'\bTODO\b', 'TODO'), (r'\bFIXME\b', 'FIXME')]:
        n = len(re.findall(pat, app))
        if n: leftovers.append(f"{label}×{n}")
    ok("کدِ اشکال‌زدایی باقی نمانده") if not leftovers else warn("باقی‌مانده: " + '، '.join(leftovers))

    for term in cfg.get('forbidden', []):
        n = len(re.findall(r'\b' + re.escape(term) + r'\b', src))
        if n: bad(f"ردِ چیزی که باید حذف می‌شد: {term} ({n} بار)")
    if cfg.get('forbidden') and not any(f.startswith('ردِ چیزی') for f in FAILS):
        ok(f"هیچ ردی از {len(cfg['forbidden'])} موردِ حذف‌شده نیست")

    # سازگاری با شِمای دیتابیس
    sch = None
    if cfg['schema']:
        for cand in (os.path.join(os.path.dirname(os.path.abspath(html_path)), cfg['schema']),
                     os.path.join(HERE, cfg['schema'])):
            if os.path.exists(cand): sch = cand; break
        if not sch: warn("فایلِ شِما پیدا نشد: " + cfg['schema'])
    if sch:
        head("۲) سازگاری با دیتابیس")
        schema = {}
        for ln in open(sch, encoding='utf-8'):
            ln = ln.strip()
            if ln and '|' in ln:
                t, c = ln.split('|'); schema[t] = set(c.split(','))
        QP = re.compile('[' + chr(34) + chr(39) + chr(96) + ']([a-z_]+)[?]([^' + chr(34) + chr(39) + chr(96) + ']*)')
        prob = []
        for m in QP.finditer(app):
            tbl, qs = m.group(1), m.group(2)
            if not re.search(r'select=|order=|limit=|=eq\.|=ilike\.', qs): continue
            if tbl not in schema: prob.append('جدولِ ناشناخته: ' + tbl); continue
            sm = re.search(r'select=([^&]*)', qs)
            if sm:
                sel = sm.group(1)
                for nt, nc in re.findall(r'([a-z_]+)!?\w*\(([^)]*)\)', sel):
                    if nt in schema:
                        for col in [x.strip().split(':')[0] for x in nc.split(',') if x.strip()]:
                            if col not in schema[nt]: prob.append(f'ستونِ تودرتو: {nt}.{col}')
                flat = re.sub(r'[a-z_]+!?\w*\([^)]*\)', '', sel)
                for col in [x.strip().split(':')[0] for x in flat.split(',') if x.strip()]:
                    if col not in ('*', '') and col not in schema[tbl]: prob.append(f'ستونِ ناموجود: {tbl}.{col}')
            for fm in re.finditer(r'(?:^|&)([a-z_]+)=(?:eq|neq|gt|gte|lt|lte|like|ilike|is|in|not)\.', qs):
                c2 = fm.group(1)
                if c2 in ('select', 'order', 'limit', 'offset', 'or', 'and'): continue
                if c2 not in schema[tbl]: prob.append(f'فیلترِ ناموجود: {tbl}.{c2}')
            om = re.search(r'order=([a-z_]+)', qs)
            if om and om.group(1) not in schema[tbl]: prob.append(f'مرتب‌سازیِ ناموجود: {tbl}.{om.group(1)}')
        prob = list(dict.fromkeys(prob))
        ok(f"هر پرس‌وجو با {len(schema)} جدولِ واقعی می‌خوانَد") if not prob else [bad(p) for p in prob]
    return src, markup, app

# ───────────────────────────── ویژگیِ زباله از HTMLِ شکسته‌ی ساخته‌شده در جاواسکریپت
# اعتبارسنجیِ متنِ HTML فقط نشانه‌گذاریِ ثابت را می‌بیند. هرچه با innerHTML ساخته می‌شود
# از آن در می‌رود، و مرورگر خودش «تعمیرش» می‌کند — روی یک دستگاه کار می‌کند، روی دیگری نه.
# نشانه‌ی این تعمیر، ویژگی‌ای است با نامِ نامعتبر (مثلاً یک گیومه‌ی اضافه).
JUNK_ATTR_SCAN = """()=>{
  const ok=/^[a-zA-Z_:][-a-zA-Z0-9_:.]*$/;
  const out=[];
  document.querySelectorAll('*').forEach(el=>{
    for(const a of el.attributes){
      if(!ok.test(a.name)){
        out.push(el.tagName.toLowerCase()+(el.id?'#'+el.id:'')+' ← ویژگیِ نامعتبر: '+JSON.stringify(a.name).slice(0,40));
      }
    }
  });
  return out.slice(0,3);
}"""

# ───────────────────────────── کشوی افقیِ ناخواسته
# بررسیِ scrollWidth روی کلِ سند، پنجره‌ای که خودش کشوی افقی دارد را نمی‌بیند:
# سند سرِ جاش می‌مانَد و کاربر باید محتوا را با انگشت بکشد کنار تا ببیندش.
HSCROLL_SCAN = """(skip)=>{
  const out=[];
  document.querySelectorAll('*').forEach(el=>{
    if(el.scrollWidth<=el.clientWidth+2||el.clientWidth<=0)return;
    if(/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))return;  // متنِ درونِ فیلد طبیعتاً می‌لغزد
    if(getComputedStyle(el).overflowX==='visible')return;   // بیرون‌زدگیِ آزاد را بررسیِ قبلی می‌گیرد
    const r=el.getBoundingClientRect(); if(r.width<50||r.height<20)return;
    if(skip.some(s=>{try{return el.matches(s)||el.closest(s)}catch(_){return false}}))return;
    out.push(el.tagName.toLowerCase()+(el.id?'#'+el.id:'.'+String(el.className||'').trim().slice(0,24))
             +' ('+el.clientWidth+'→'+el.scrollWidth+')');
  });
  return out.slice(0,3);
}"""

# ───────────────────────────── کادرِ روشنِ جامانده در تمِ تیره
# «صفحه در تمِ تاریک باز شد» شاهد نیست — رنگِ ثابتِ روشن باید اندازه گرفته شود.
PAGE_IS_DARK = """()=>{
  const f=v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)};
  const m=String(getComputedStyle(document.body).backgroundColor).match(/rgba?\\(([^)]+)\\)/);
  if(!m)return false; const p=m[1].split(',').map(parseFloat);
  return (.2126*f(p[0])+.7152*f(p[1])+.0722*f(p[2]))<0.35;
}"""

# فقط چیزی که واقعاً آزاردهنده است: کادرِ متن‌دارِ خیلی روشن.
# عکس و آیکن و هرچه زیرِ .force-light است (عمداً روشن می‌مانَد) کنار گذاشته می‌شود.
LIGHT_BOX_SCAN = """()=>{
  const f=v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)};
  const lum=p=>.2126*f(p[0])+.7152*f(p[1])+.0722*f(p[2]);
  const rgb=s=>{const m=String(s).match(/rgba?\\(([^)]+)\\)/); if(!m)return null;
    const p=m[1].split(',').map(parseFloat); if(p.length>3&&p[3]<0.5)return null; return p};
  const out=[];
  document.querySelectorAll('*').forEach(el=>{
    if(el.closest('.force-light'))return;
    if(/^(IMG|SVG|CANVAS|VIDEO|PATH|RECT|LINE|TEXT)$/.test(el.tagName))return;
    const r=el.getBoundingClientRect(); if(r.width<40||r.height<18)return;
    const cs=getComputedStyle(el);
    if(cs.visibility==='hidden'||cs.display==='none'||+cs.opacity<0.1)return;
    if(!(el.innerText||'').trim())return;
    let c=rgb(cs.backgroundColor);
    if(!c){ const bi=cs.backgroundImage;
      if(bi&&bi!=='none'){ const m=bi.match(/rgba?\\([^)]+\\)/g); if(m)c=rgb(m[0]); } }
    if(!c)return;
    if(lum(c)>0.85) out.push({sig:el.tagName.toLowerCase()+'.'+String(el.className||'').trim().slice(0,26),
                              txt:(el.innerText||'').replace(/\\s+/g,' ').trim().slice(0,40)});
  });
  return out;
}"""

# ───────────────────────────── سرورِ محلی
def serve(html_path, extra):
    root = '/tmp/_audit_srv'
    os.makedirs(root, exist_ok=True)
    import shutil
    shutil.copy(html_path, os.path.join(root, 'index.html'))
    base = os.path.dirname(os.path.abspath(html_path))
    for f in extra:
        p = os.path.join(base, f)
        if os.path.exists(p): shutil.copy(p, os.path.join(root, os.path.basename(f)))
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(('127.0.0.1', 8931),
                                 functools.partial(Q, directory=root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, 'http://127.0.0.1:8931/index.html'

# ───────────────────────────── زنده (مرورگر)
def runtime_checks(url, cfg, html_path):
    from playwright.sync_api import sync_playwright
    fixture = ''
    if cfg['fixture']:
        for cand in (os.path.join(os.path.dirname(os.path.abspath(html_path)), cfg['fixture']),
                     os.path.join(HERE, cfg['fixture'])):   # نامِ صریح در تنظیمات لازم است
            if os.path.exists(cand): fixture = open(cand, encoding='utf-8').read(); break
        if not fixture: warn("فایلِ شبیه‌ساز پیدا نشد: " + cfg['fixture'])

    errs, netfail = [], []
    shots = '/tmp/audit_shots'; os.makedirs(shots, exist_ok=True)
    for f in os.listdir(shots):
        try: os.remove(os.path.join(shots, f))
        except Exception: pass

    with sync_playwright() as pw:
        # پرچمِ پخشِ خودکار لازم است وگرنه مسیرِ فشرده‌سازیِ فیلم اصلاً اجرا نمی‌شود
        br = pw.chromium.launch(args=['--autoplay-policy=no-user-gesture-required','--mute-audio'])
        pg = br.new_page(viewport={'width': 412, 'height': 900})
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.on('response', lambda r: netfail.append(f"{r.status} {r.url[:80]}") if r.status >= 400 else None)
        pg.on('dialog', lambda d: d.accept())
        if fixture: pg.add_init_script(fixture)
        pg.add_init_script("document.addEventListener('securitypolicyviolation',e=>{(window.__CSP=window.__CSP||[]).push(e.violatedDirective+' → '+e.blockedURI.slice(0,60))});")

        head("۳) بالا آمدن")
        pg.goto(url); pg.wait_for_timeout(600)
        boot_errs = list(errs)
        ok("صفحه بدونِ خطا بالا می‌آید") if not boot_errs else [bad("خطای شروع: " + e[:110]) for e in boot_errs]

        for step in cfg['login']:
            try:
                if 'fill' in step: pg.fill(step['fill'], step.get('value', ''))
                elif 'click' in step: pg.click(step['click'])
                elif 'js' in step: pg.evaluate(step['js'])
                pg.wait_for_timeout(step.get('wait', 250))
            except Exception as ex: warn("مرحله‌ی ورود رد شد: " + str(ex)[:70])
        if cfg['login']: pg.wait_for_timeout(900)

        # بدونِ این، ورودِ نیمه‌کاره خودش را به‌شکلِ ده‌ها «باگ» جعلی نشان می‌دهد:
        # صفحه‌ی ورود سرِ جایش می‌ماند، هر کلیک timeout می‌دهد و هر بررسی صفر برمی‌گرداند.
        if cfg['login_done']:
            try:
                pg.wait_for_function(cfg['login_done'], timeout=25000)
                ok("برنامه بعد از ورود واقعاً آماده شد")
            except Exception:
                bad("بعد از ورود برنامه آماده نشد — ورود ناموفق بوده، نه برنامه خراب")
                print("     ادامه نمی‌دهم: روی صفحه‌ی ورود، هر کلیک timeout می‌دهد و هر")
                print("     بررسی صفر برمی‌گرداند و ده‌ها باگِ جعلی ساخته می‌شود.")
                print("     اول مرحله‌ی login در تنظیمات را درست کن.")
                br.close(); return

        screens = [tuple(s) for s in cfg['screens']]
        guessed = not screens
        if not screens:
            cand = sorted({m.group(1) for m in re.finditer(r'onclick="([a-zA-Z_$][\w$]*\(\s*\))"', open(html_path, encoding='utf-8').read())})
            screens = [(c[:-2], c) for c in cand[:25]]
            if screens: warn(f"فهرستِ صفحه‌ها در تنظیمات نبود — {len(screens)} تا خودکار پیدا شد")

        # اگر عبارتِ یک صفحه Promiseای برگرداند که هیچ‌وقت resolve نمی‌شود (مثلاً پنجره‌ی
        # پرسشی که منتظرِ کلیک است)، pg.evaluate تا ابد منتظر می‌مانَد و کلِ اجرا می‌خوابد.
        SCREEN_MS = 8000
        def screen_eval(js):
            try:
                return pg.evaluate("()=>Promise.race(["
                                   "Promise.resolve().then(()=>(" + js + ")),"
                                   "new Promise(r=>setTimeout(()=>r('__TIMEOUT__')," + str(SCREEN_MS) + "))])")
            except Exception as ex:
                if 'SyntaxError' in str(ex): return pg.evaluate(js)   # عبارتِ چندجمله‌ای
                raise

        head("۴) باز شدنِ همه‌ی صفحه‌ها")
        broke = []
        for nm, js in screens:
            n0 = len(errs)
            try:
                if cfg['reset']: pg.evaluate(cfg['reset'])
                if screen_eval(js) == '__TIMEOUT__':
                    broke.append(f"{nm}: تا {SCREEN_MS//1000} ثانیه جواب نداد (Promiseی که resolve نمی‌شود؟)")
                    continue
                pg.wait_for_timeout(190)
                if len(errs) > n0: broke.append(f"{nm}: {errs[n0][:80]}")
            except Exception as ex: broke.append(f"{nm}: {str(ex)[:80]}")
        if not broke: ok(f"هر {len(screens)} صفحه بدونِ خطا باز شد")
        elif guessed:
            warn(f"{len(broke)} تابعِ حدس‌زده خطا داد (شاید بی‌بافت صدا زده شده) — برای دقتِ کامل screens را در تنظیمات بنویس")
            for b in broke[:4]: print("       · " + b[:95])
        else: [bad(b) for b in broke]

        v = pg.evaluate("()=>window.__CSP||[]")
        ok("قفلِ امنیتی جلوی هیچ منبعی را نگرفت") if not v else [bad("قفلِ امنیتی: " + x) for x in v]
        outside = [f for f in netfail if '127.0.0.1' not in f]
        ok("همه‌ی درخواست‌ها موفق بودند") if not outside \
            else [warn("درخواستِ ناموفق: " + f) for f in list(dict.fromkeys(outside))[:5]]


        head("۴.۵) سلامتِ دستورهای درون‌خطی")
        broken = {}
        for name, js in screens:
            try:
                if cfg['reset']: pg.evaluate(cfg['reset'])
                pg.evaluate(js); pg.wait_for_timeout(220)
                bad_h = pg.evaluate("""()=>{ const out=[];
                  const EV=['onclick','onchange','oninput','onsubmit','onkeyup','onkeydown','onblur','onfocus'];
                  for(const e of document.querySelectorAll('*')){
                    for(const a of EV){
                      const v=e.getAttribute&&e.getAttribute(a); if(!v) continue;
                      try{ new Function(v); }
                      catch(err){ out.push(a+'="'+v.slice(0,42)+'" روی '+((e.id||String(e.className)).slice(0,20)||e.tagName)); }
                    }
                  }
                  return [...new Set(out)].slice(0,4); }""")
                for x in bad_h: broken.setdefault(x, name)
            except Exception: pass
        ok("هر دستورِ درون‌خطی (onclick و مانندش) نحوِ درست دارد") if not broken \
            else [bad(f"دستورِ شکسته در «{v}»: {k}") for k, v in list(broken.items())[:5]]

        junk = {}
        for name, js in screens:
            try:
                if cfg['reset']: pg.evaluate(cfg['reset'])
                pg.evaluate(js); pg.wait_for_timeout(200)
                for x in pg.evaluate(JUNK_ATTR_SCAN): junk.setdefault(x, name)
            except Exception: pass
        ok("نشانه‌گذاریِ ساخته‌شده در جاواسکریپت سالم است") if not junk \
            else [bad(f"HTMLِ شکسته که مرورگر ترمیمش کرده — «{v}»: {k}") for k, v in list(junk.items())[:5]]

        head("۵) مقدارِ خراب در متن")
        leaks = []
        for nm, js in screens:
            try:
                if cfg['reset']: pg.evaluate(cfg['reset'])
                pg.evaluate(js); pg.wait_for_timeout(150)
                t = pg.evaluate("""()=>[...document.querySelectorAll('body *:not(script):not(style):not(template)')]
                      .filter(e=>e.children.length===0).map(e=>e.textContent).join(' | ')""")
                for w in ['NaN', 'undefined', 'Infinity', '[object']:
                    if w in t: leaks.append(f"{nm} → {w}")
            except Exception: pass
        ok("هیچ NaN/undefined/Infinity در صفحه‌ها نیست") if not leaks \
            else [bad("مقدارِ خراب: " + l) for l in list(dict.fromkeys(leaks))[:6]]

        head("۶) لمس‌پذیریِ دکمه‌ها")
        if cfg['reset']: pg.evaluate(cfg['reset'])
        if screens: pg.evaluate(screens[0][1]); pg.wait_for_timeout(500)
        blocked = pg.evaluate("""()=>{ const out=[];
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
        ok("هیچ دکمه‌ای زیرِ چیزِ دیگری گیر نکرده") if not blocked else [bad("دکمه‌ی مسدود: " + x) for x in blocked]


        head("۶.۵) عنصرهای چسبیده به صفحه")
        swallow = pg.evaluate("""()=>{ const out=[];
          const OVL='.overlay,[data-overlay],dialog,.modal,.sheet,.drawer';
          for(const e of document.querySelectorAll('*')){
            const cs=getComputedStyle(e);
            if(cs.position!=='fixed'&&cs.position!=='sticky') continue;
            if(e.matches(OVL)) continue;              // پنجره طبیعتاً محتوا دارد
            if(e.closest(OVL)!==null && e.closest(OVL)!==e) continue;
            const holds=e.querySelector('main, .screen, '+OVL);
            if(holds)
              out.push((e.id||String(e.className).slice(0,26)||e.tagName)+' — «'+
                       (holds.id||String(holds.className).slice(0,20)||holds.tagName)+'» داخلش افتاده');
          }
          return out.slice(0,5); }""")
        ok("هیچ نوار یا عنصرِ چسبیده‌ای محتوای صفحه را در خود نگرفته") if not swallow \
            else [bad("عنصرِ چسبیده محتوا را بلعیده: " + x) for x in swallow]


        if cfg.get('click_test'):
            head("۶.۷) کلیکِ واقعی روی دکمه‌ها")
            ct = cfg['click_test']
            sel = ct.get('selector', 'button')
            if cfg['reset']: pg.evaluate(cfg['reset'])
            if ct.get('before'): pg.evaluate(ct['before']); pg.wait_for_timeout(ct.get('wait', 500))
            els = pg.query_selector_all(sel)
            dead = []
            for el in els:
                lbl = ((el.inner_text() or '').split(chr(10))[0].strip() or 'دکمه')[:22]
                try:
                    sig0 = pg.evaluate("()=>document.body.innerHTML.length + '|' + [...document.querySelectorAll('.overlay,dialog,.modal')].filter(o=>!o.classList.contains('hidden')).length")
                    el.click(timeout=2500); pg.wait_for_timeout(ct.get('settle', 450))
                    sig1 = pg.evaluate("()=>document.body.innerHTML.length + '|' + [...document.querySelectorAll('.overlay,dialog,.modal')].filter(o=>!o.classList.contains('hidden')).length")
                    if sig0 == sig1: dead.append(lbl + ' (هیچ اتفاقی نیفتاد)')
                    if cfg['reset']: pg.evaluate(cfg['reset'])
                    if ct.get('before'): pg.evaluate(ct['before']); pg.wait_for_timeout(200)
                except Exception as ex:
                    dead.append(lbl + ' 💥 ' + str(ex)[:45])
            ok(f"هر {len(els)} دکمه با کلیکِ واقعی کار کرد") if not dead \
                else [bad("دکمه‌ی بی‌اثر: " + d) for d in dead]


        head("۶.۶) لایه‌بندی (z-index)")
        layers = pg.evaluate("""()=>{ const z={};
          for(const e of document.querySelectorAll('body *')){
            const v=getComputedStyle(e).zIndex;
            if(v&&v!=='auto'&&+v>0) (z[+v]=z[+v]||[]).push((e.id||String(e.className)).slice(0,22)); }
          return Object.entries(z).map(([k,v])=>[+k,[...new Set(v)]]).sort((a,b)=>b[0]-a[0]); }""")
        ovz = pg.evaluate("""()=>{ const o=document.querySelector('.overlay,[data-overlay],dialog,.modal');
          return o?+getComputedStyle(o).zIndex||0:0; }""")
        wild = [f"{k} ({'، '.join(v[:2])})" for k, v in layers if k > 1000]
        ok("هیچ لایه‌ی خودسرانه‌ای بالاتر از مقیاسِ نام‌دار نیست") if not wild \
            else [bad("z-index خارج از مقیاس: " + w) for w in wild]
        if ovz:
            above = [f"{k} ({'، '.join(v[:2])})" for k, v in layers
                     if k > ovz and not any(('overlay' in x or 'toast' in x or 'modal' in x or 'dialog' in x) for x in v)]
            ok(f"هیچ عنصرِ ثابتی بالاتر از پنجره‌ها ({ovz}) ننشسته") if not above \
                else [bad("بالاتر از پنجره‌ها می‌نشیند و لمس را می‌گیرد: " + a) for a in above]

        head("۷) پنجره‌ها (شفافیت)")
        ovs = pg.evaluate("()=>[...document.querySelectorAll('.overlay,[data-overlay],dialog,.modal')].map(o=>o.id||o.className).slice(0,20)")
        if not ovs:
            warn("پنجره‌ای پیدا نشد — این بررسی رد شد")
        else:
            seethrough = []
            for nm, js in screens:
                try:
                    if cfg['reset']: pg.evaluate(cfg['reset'])
                    pg.evaluate(js); pg.wait_for_timeout(320)
                    r = pg.evaluate("""()=>{ const o=[...document.querySelectorAll('.overlay,[data-overlay],dialog,.modal')]
                        .find(x=>!x.classList.contains('hidden') && x.offsetWidth>200);
                      if(!o) return null;
                      const alpha=(el)=>{ const bg=getComputedStyle(el).backgroundColor;
                        const p=(bg.match(/[\\d.]+/g)||[]).map(Number);
                        return {bg, a:p.length>3?p[3]:1}; };
                      let v=alpha(o);
                      // الگوی امروزی: خودِ <dialog> شفاف است و کارتِ داخلش پس‌زمینه دارد.
                      // آن هم پوشاننده است، پس بچه‌ی اولش را می‌سنجیم نه خودش را.
                      if(v.a<0.95 && o.firstElementChild){
                        const c=alpha(o.firstElementChild);
                        const r=o.getBoundingClientRect(), cr=o.firstElementChild.getBoundingClientRect();
                        if(c.a>=0.95 && cr.width>=r.width*0.9 && cr.height>=r.height*0.9) v=c;
                      }
                      return {id:o.id||o.className, bg:v.bg, a:v.a}; }""")
                    if r and r['a'] < 0.95: seethrough.append(f"{nm} ({r['bg']})")
                except Exception: pass
            seethrough = list(dict.fromkeys(seethrough))
            ok(f"هر پنجره‌ای که باز شد پس‌زمینه‌ی توپُر داشت") if not seethrough \
                else [bad("پنجره‌ی شفاف — پشتش دیده می‌شود: " + s) for s in seethrough]

        head("۸) صفحه‌ی باریک (" + str(cfg['narrow_width']) + " پیکسل)")
        pg.set_viewport_size({'width': cfg['narrow_width'], 'height': 800})
        overflow = []
        for nm, js in screens:
            try:
                if cfg['reset']: pg.evaluate(cfg['reset'])
                pg.evaluate(js); pg.wait_for_timeout(190)
                r = pg.evaluate("""()=>{ const w=document.documentElement.clientWidth;
                  if(document.documentElement.scrollWidth<=w+2) return null;
                  const off=[...document.querySelectorAll('body *')].filter(e=>{
                    const r=e.getBoundingClientRect(); return r.width>0 && r.right>w+2 && getComputedStyle(e).position!=='fixed'; })
                    .map(e=>(e.className&&String(e.className).slice(0,24))||e.tagName);
                  return off.slice(0,2); }""")
                if r: overflow.append(f"{nm}: {r}")
            except Exception: pass
        pg.set_viewport_size({'width': 412, 'height': 900})
        ok("در صفحه‌ی باریک چیزی از کادر بیرون نمی‌زند") if not overflow \
            else [warn("بیرون‌زدگی: " + o) for o in overflow[:4]]

        head("۸.۵) کشوی افقیِ ناخواسته")
        skip = cfg['allow_hscroll']
        hs = []
        for w in (cfg['narrow_width'], 412):
            pg.set_viewport_size({'width': w, 'height': 900})
            for nm, js in screens:
                try:
                    if cfg['reset']: pg.evaluate(cfg['reset'])
                    pg.evaluate(js); pg.wait_for_timeout(190)
                    for r in pg.evaluate(HSCROLL_SCAN, skip):
                        line = f"{nm} در {w}px: {r}"
                        if line not in hs: hs.append(line)
                except Exception: pass
        pg.set_viewport_size({'width': 412, 'height': 900})
        ok("هیچ پنجره‌ای کشوی افقیِ ناخواسته ندارد") if not hs \
            else [bad("کشوی افقی — " + h) for h in hs[:5]]

        head("۹) تم‌ها")
        themes = cfg['themes']
        if not themes:
            has = pg.evaluate("()=>!!document.querySelector('[data-theme]')||/data-theme/.test(document.documentElement.outerHTML.slice(0,4000))")
            if has: themes = [{"name": "تاریک", "js": "document.documentElement.setAttribute('data-theme','dark')"},
                              {"name": "روشن", "js": "document.documentElement.setAttribute('data-theme','light')"}]
        if not themes:
            warn("تمِ دومی پیدا نشد — این بررسی رد شد")
        else:
            for th in themes:
                pg.evaluate(th['js']); pg.wait_for_timeout(250)
                tbroke = []
                for nm, js in screens:
                    n0 = len(errs)
                    try:
                        if cfg['reset']: pg.evaluate(cfg['reset'])
                        pg.evaluate(js); pg.wait_for_timeout(140)
                        if len(errs) > n0: tbroke.append(f"{nm}: {errs[n0][:60]}")
                    except Exception as ex: tbroke.append(f"{nm}: {str(ex)[:60]}")
                if not tbroke: ok(f"همه‌ی صفحه‌ها در تمِ {th['name']} هم سالم‌اند")
                elif guessed: warn(f"تمِ {th['name']}: {len(tbroke)} تابعِ حدس‌زده خطا داد")
                else: [bad(f"تمِ {th['name']} — " + t) for t in tbroke]

                # «باز شد» شاهد نیست: تو تمِ تیره دنبالِ کادرِ روشنِ جامانده بگرد
                if pg.evaluate(PAGE_IS_DARK):
                    light = []
                    for nm, js in screens:
                        try:
                            if cfg['reset']: pg.evaluate(cfg['reset'])
                            pg.evaluate(js); pg.wait_for_timeout(160)
                            for r in pg.evaluate(LIGHT_BOX_SCAN):
                                sig = (r['sig'], r['txt'])
                                if sig not in [(x['sig'], x['txt']) for x in light]:
                                    r['screen'] = nm; light.append(r)
                        except Exception: pass
                    if not light: ok(f"در تمِ {th['name']} کادرِ روشنِ جامانده‌ای نیست")
                    else: [bad(f"کادرِ روشن در تمِ {th['name']} — {l['screen']}: {l['sig']} «{l['txt']}»") for l in light[:5]]

        if cfg['checks']:
            head("۱۰) بررسی‌های ویژه‌ی پروژه")
            for c in cfg['checks']:
                try:
                    if c.get('before'):
                        if cfg['reset']: pg.evaluate(cfg['reset'])
                        pg.evaluate(c['before']); pg.wait_for_timeout(c.get('wait', 400))
                    got = pg.evaluate(c['js'])
                    exp = c['expect']
                    ok(f"{c['name']}: {got}") if str(got) == str(exp) else bad(f"{c['name']}: {got} ≠ انتظار {exp}")
                except Exception as ex: bad(f"{c['name']}: 💥 {str(ex)[:80]}")

        head("۱۱) عکس‌برداری")
        shot_n = 0
        for nm, js in screens[:30]:
            try:
                if cfg['reset']: pg.evaluate(cfg['reset'])
                pg.evaluate(js); pg.wait_for_timeout(420)
                safe = re.sub(r'[^\w\u0600-\u06FF]+', '_', nm)[:24]
                pg.screenshot(path=f"{shots}/{shot_n:02d}_{safe}.png"); shot_n += 1
            except Exception: pass
        ok(f"{shot_n} عکس در {shots} ذخیره شد — حتماً چندتا را با چشم ببین")
        br.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('html'); ap.add_argument('-c', '--config', default=None)
    a = ap.parse_args()
    cfg = load_cfg(a.config, a.html)
    print("\n" + "═" * 52)
    print("  بازرسِ عمومی — پروژه: " + cfg['name'])
    print("═" * 52)
    static_checks(a.html, cfg)
    srv, url = serve(a.html, cfg['assets'])
    try: runtime_checks(url, cfg, a.html)
    finally: srv.shutdown()
    print("\n" + "═" * 52)
    print(f"  {len(PASSES)} بررسی پاس شد")
    if WARNS: print(f"  ⚠️  {len(WARNS)} هشدارِ غیربحرانی")
    if FAILS:
        print(f"  ❌ {len(FAILS)} ایراد — تحویل نده:")
        for f in FAILS: print("     • " + f)
    else:
        print("  ✅ آماده‌ی تحویل")
    sys.exit(1 if FAILS else 0)

if __name__ == '__main__':
    main()
