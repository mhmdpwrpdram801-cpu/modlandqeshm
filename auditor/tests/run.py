#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تستِ خودِ بازرس.

    python3 tests/run.py            # همه
    python3 tests/run.py a11y forms # فقط چند تست

هر بررسیِ تازه دو نمونه دارد: یکی که عمداً همان باگ را دارد (باید گرفته شود)
و یکی سالم (نباید قرمز بدهد). بدونِ این دو، بررسیِ تازه قبول نیست.
خروجی: کدِ ۰ یعنی خودِ بازرس سالم است.
"""
import os, sys, json, time, shutil, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.join(os.path.dirname(HERE), 'audit.py')
FIX = os.path.join(HERE, 'fixtures')
TMP = os.path.join(tempfile.gettempdir(), 'audit_selftest')

PASSED, FAILED = [], []

def run(rel, only=None, state=None, save=False, config=None, extra=None):
    """بازرس را روی یک نمونه اجرا می‌کند و گزارشِ ماشین‌خوان را برمی‌گرداند."""
    html = rel if os.path.isabs(rel) else os.path.join(FIX, rel, 'index.html')
    out = os.path.join(TMP, 'report.json')
    cmd = [sys.executable, AUDIT, html, '--json', out]
    if only: cmd += ['--only', only]
    cmd += ['--state', state or os.path.join(TMP, 'state_throwaway')]
    if not save: cmd += ['--no-save']
    if config: cmd += ['-c', os.path.join(FIX, rel, config)]
    cmd += (extra or [])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if not os.path.exists(out):
        raise RuntimeError("بازرس گزارشی نداد:\n" + (p.stdout or '')[-1500:] + (p.stderr or '')[-800:])
    return json.load(open(out, encoding='utf-8'))

def lv(rep, key):
    for r in rep['results']:
        if r['key'] == key: return r['level']
    return None

def any_lv(rep, prefix, level):
    return [r for r in rep['results'] if r['key'].startswith(prefix) and r['level'] == level]

def sect(rep, sid, level):
    return [r for r in rep['results'] if r['section'] == sid and r['level'] == level]

def check(name, cond, detail=''):
    (PASSED if cond else FAILED).append(name + (('  ← ' + detail) if detail and not cond else ''))
    print(("  ✅ " if cond else "  ❌ ") + name + (("  ← " + detail) if detail and not cond else ''))

# ═══════════════ تست‌های اعلانی: نمونه‌ی باگ‌دار / نمونه‌ی سالم
CASES = [
    dict(id='a11y', name='دسترس‌پذیری — نمونه‌ی باگ‌دار گرفته می‌شود', path='a11y/bad', only='a11y',
         warn=['a11y/touch', 'a11y/label', 'a11y/placeholder', 'a11y/alt'],
         warn_prefix=['a11y/focus/']),
    dict(id='a11y', name='دسترس‌پذیری — نمونه‌ی سالم قرمز نمی‌دهد', path='a11y/good', only='a11y',
         clean=['a11y'], passes=['a11y/touch', 'a11y/label', 'a11y/alt', 'a11y/focus']),

    dict(id='forms', name='فرم — ورودیِ مرزی باگ را رو می‌کند', path='forms/bad', only='forms',
         fail_prefix=['forms/'], warn_prefix=['forms/leak/']),
    dict(id='forms', name='فرم — نمونه‌ی سالم قرمز نمی‌دهد', path='forms/good', only='forms',
         clean=['forms'], passes=['forms/crash', 'forms/leak']),

    dict(id='bundle', name='حجم — کتابخانه‌ی سنگینِ شروع دیده می‌شود', path='bundle/bad', only='bundle',
         warn_prefix=['bundle/']),
    dict(id='bundle', name='حجم — کتابخانه‌ی کوچک هشدار نمی‌دهد', path='bundle/good', only='bundle',
         clean=['bundle'], passes=['bundle/all']),

    dict(id='sw', name='SW — فایلِ نبودِ فهرستِ کش ایراد است', path='sw/bad', only='sw',
         fail=['sw/./missing.js']),
    dict(id='sw', name='SW — فهرستِ درست ایراد نمی‌دهد', path='sw/good', only='sw',
         clean=['sw'], passes=['sw/all']),

    dict(id='dom', name='شناسه‌ی پویا (q+i) اشتباهاً «گمشده» گزارش نمی‌شود',
         path='dom_dynamic/good', only='dom', clean=['dom'], passes=['dom/all']),

    dict(id='sql', name='SQL — بدونِ اتصال، دستور چاپ می‌شود و هشدار می‌ماند (نه ایراد)',
         path='sql/one', only='sql', warn=['sql/skipped']),
]

def run_case(c):
    rep = run(c['path'], only=c.get('only'))
    okall = True
    for k in c.get('fail', []):
        if lv(rep, k) != 'fail': okall = False; check(c['name'], False, "کلیدِ %s ایراد نشد (%s)" % (k, lv(rep, k))); break
    else:
        for k in c.get('warn', []):
            if lv(rep, k) != 'warn': okall = False; check(c['name'], False, "کلیدِ %s هشدار نشد (%s)" % (k, lv(rep, k))); break
        else:
            for p in c.get('fail_prefix', []):
                if not any_lv(rep, p, 'fail'): okall = False; check(c['name'], False, "هیچ ایرادی با پیشوندِ " + p); break
            else:
                for p in c.get('warn_prefix', []):
                    if not any_lv(rep, p, 'warn'): okall = False; check(c['name'], False, "هیچ هشداری با پیشوندِ " + p); break
                else:
                    for k in c.get('passes', []):
                        if lv(rep, k) != 'pass': okall = False; check(c['name'], False, "کلیدِ %s پاس نشد (%s)" % (k, lv(rep, k))); break
                    else:
                        for s in c.get('clean', []):
                            dirt = sect(rep, s, 'fail') + sect(rep, s, 'warn')
                            if dirt:
                                okall = False
                                check(c['name'], False, "بخشِ %s تمیز نبود: %s" % (s, dirt[0]['msg'][:70])); break
                        else:
                            check(c['name'], True)
    return okall

# ═══════════════ تست‌های چندمرحله‌ای
def t_visual_change():
    st = os.path.join(TMP, 'vis_change'); shutil.rmtree(st, ignore_errors=True)
    run('visual/v1', only='shots,visual', state=st, save=True)
    rep = run('visual/v2', only='shots,visual', state=st)
    check('تصویری — تغییرِ واقعیِ صفحه گزارش می‌شود',
          bool(any_lv(rep, 'visual/', 'warn')), 'هیچ هشدارِ تصویری نیامد')

def t_visual_stable():
    st = os.path.join(TMP, 'vis_stable'); shutil.rmtree(st, ignore_errors=True)
    run('visual/v1', only='shots,visual', state=st, save=True)
    rep = run('visual/v1', only='shots,visual', state=st)
    check('تصویری — صفحه‌ی بدونِ تغییر هشدار نمی‌دهد',
          lv(rep, 'visual/all') == 'pass',
          'هشدارِ الکی: ' + str([r['msg'] for r in sect(rep, 'visual', 'warn')][:1]))

def t_visual_clock():
    st = os.path.join(TMP, 'vis_clock'); shutil.rmtree(st, ignore_errors=True)
    run('visual/clock', only='shots,visual', state=st, save=True)
    time.sleep(1)
    rep = run('visual/clock', only='shots,visual', state=st)
    check('تصویری — ناحیه‌ی پویا (ساعت) نادیده گرفته می‌شود',
          lv(rep, 'visual/all') == 'pass',
          'هشدارِ کاذب: ' + str([r['msg'] for r in sect(rep, 'visual', 'warn')][:1]))

def t_visual_clock_unmasked():
    st = os.path.join(TMP, 'vis_clock_raw'); shutil.rmtree(st, ignore_errors=True)
    run('visual/clock', only='shots,visual', state=st, save=True, config='noignore.config.json')
    time.sleep(1)
    rep = run('visual/clock', only='shots,visual', state=st, config='noignore.config.json')
    check('تصویری — بدونِ ماسک همان ساعت تغییر گزارش می‌شود (یعنی ماسک واقعاً کار می‌کند)',
          bool(any_lv(rep, 'visual/', 'warn')), 'بدونِ ماسک هم چیزی گزارش نشد؛ آزمونِ ماسک بی‌معنی است')

def _big_lib_project(where, call_them):
    """پروژه‌ای با یک کتابخانه‌ی ۱۲۰ کیلوبایتی — یک‌بار بلااستفاده، یک‌بار کاملاً استفاده‌شده.
    (فایلِ بزرگ را در مخزن نگه نمی‌داریم؛ همین‌جا ساخته می‌شود.)"""
    os.makedirs(where, exist_ok=True)
    body = ''.join('var v%d = %d;\n' % (j, j) for j in range(28))
    lib = '/*! biglib 1.0 */\n' + ''.join('function f%d(){\n%s}\n' % (i, body) for i in range(300))
    use = 'for (var i = 0; i < 300; i++) window["f" + i]();\n' if call_them else '// صدا زده نمی‌شود\n'
    open(os.path.join(where, 'index.html'), 'w', encoding='utf-8').write(
        '<!DOCTYPE html><html dir="rtl" lang="fa"><head><meta charset="UTF-8">'
        '<title>پوشش</title></head><body>\n<div id="x">سلام</div>\n'
        '<script>\n' + lib + '</script>\n'
        '<script>\n' + use + 'function go(){ document.getElementById("x").textContent = "ok"; }\n'
        '</script>\n</body></html>\n')
    json.dump({"name": "پوشش", "screens": [["اصلی", "1"]], "heavy_inline_kb": 999},
              open(os.path.join(where, 'audit.config.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    return os.path.join(where, 'index.html')

def t_coverage():
    idle = _big_lib_project(os.path.join(TMP, 'cov_idle'), call_them=False)
    rep = run(idle, only='coverage', extra=['--deep'])
    check('پوشش — کتابخانه‌ی سنگینِ بلااستفاده گرفته می‌شود',
          bool(any_lv(rep, 'coverage/', 'warn')),
          str([r['msg'][:70] for r in rep['results'] if r['section'] == 'coverage']))
    used = _big_lib_project(os.path.join(TMP, 'cov_used'), call_them=True)
    rep = run(used, only='coverage', extra=['--deep'])
    check('پوشش — کتابخانه‌ی واقعاً استفاده‌شده هشدار نمی‌دهد',
          lv(rep, 'coverage/all') == 'pass',
          str([r['msg'][:70] for r in rep['results'] if r['section'] == 'coverage']))
    rep = run(idle, only='coverage')
    check('پوشش بدونِ --deep اصلاً اجرا نمی‌شود (سرعت)', rep['sections_run'] == [], str(rep['sections_run']))

def t_regression_fixed():
    st = os.path.join(TMP, 'reg_fixed'); shutil.rmtree(st, ignore_errors=True)
    run('forms/bad', only='forms', state=st, save=True)
    rep = run('forms/good', only='forms', state=st)
    check('رگرسیون — «چه چیزی درست شد» گزارش می‌شود',
          bool(rep['regression']['fixed']), 'فهرستِ fixed خالی بود')

def t_regression_broke():
    st = os.path.join(TMP, 'reg_broke'); shutil.rmtree(st, ignore_errors=True)
    run('forms/good', only='forms', state=st, save=True)
    rep = run('forms/bad', only='forms', state=st)
    check('رگرسیون — «چه چیزی تازه خراب شد» گزارش می‌شود',
          bool(rep['regression']['broke']), 'فهرستِ broke خالی بود')

def t_cli():
    p = subprocess.run([sys.executable, AUDIT, '--list'], capture_output=True, text=True)
    check('--list فهرستِ بخش‌ها را می‌دهد', 'a11y' in p.stdout and 'visual' in p.stdout)
    rep = run('forms/good', only='ids')
    check('--only فقط همان بخش را اجرا می‌کند', rep['sections_run'] == ['ids'], str(rep['sections_run']))
    rep = run('forms/good', only='ids,dom,ghost', extra=['--skip', 'dom'])
    check('--skip بخش را کنار می‌گذارد', 'dom' not in rep['sections_run'], str(rep['sections_run']))
    check('گزارشِ ماشین‌خوان شمارش و زمان‌بندی دارد',
          'counts' in rep and 'timings' in rep and 'exit' in rep)
    p = subprocess.run([sys.executable, AUDIT, os.path.join(FIX, 'forms/bad/index.html'),
                        '--only', 'forms', '--no-save', '--state', os.path.join(TMP, 'x')],
                       capture_output=True, text=True, timeout=600)
    check('نمونه‌ی باگ‌دار کدِ خروجیِ ۱ می‌دهد', p.returncode == 1, 'کدِ خروجی: %d' % p.returncode)
    p = subprocess.run([sys.executable, AUDIT, os.path.join(FIX, 'forms/good/index.html'),
                        '--only', 'forms', '--no-save', '--state', os.path.join(TMP, 'x')],
                       capture_output=True, text=True, timeout=600)
    check('نمونه‌ی سالم کدِ خروجیِ ۰ می‌دهد', p.returncode == 0, 'کدِ خروجی: %d' % p.returncode)

def t_missing_node():
    """نبودِ node نباید کلِ بازرسی را بیندازد — فقط یک پیامِ روشن."""
    out = os.path.join(TMP, 'nonode.json')
    env = dict(os.environ, PATH='/nonexistent-bin')
    p = subprocess.run([sys.executable, AUDIT, os.path.join(FIX, 'forms/good/index.html'),
                        '--only', 'syntax,ids', '--no-save', '--json', out,
                        '--state', os.path.join(TMP, 'x')],
                       capture_output=True, text=True, env=env, timeout=300)
    rep = json.load(open(out, encoding='utf-8'))
    check('نبودِ node پیامِ روشن می‌دهد و بقیه‌ی بررسی‌ها ادامه می‌یابد',
          lv(rep, 'syntax/node') == 'warn' and lv(rep, 'ids/all') == 'pass' and p.returncode == 0,
          'کدِ خروجی %d، syntax=%s، ids=%s' % (p.returncode, lv(rep, 'syntax/node'), lv(rep, 'ids/all')))

def t_no_config_leak():
    """تنظیماتِ پروژه‌ی الف نباید به پروژه‌ی ب بچسبد."""
    rep = run('bundle/good', only='bundle')
    check('تنظیمات از کنارِ خودِ پروژه خوانده می‌شود، نه پروژه‌ی دیگر',
          rep['project'] == 'حجم سالم', 'نامِ پروژه: ' + str(rep['project']))

def t_real_project():
    """روی یک پروژه‌ی واقعیِ سالم، تعدادِ هشدارها نباید زیاد شود."""
    real = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'index.html')
    if not os.path.exists(real):
        print("  ⏭️  پروژه‌ی واقعی کنارِ بازرس نیست — این تست رد شد"); return
    rep = run(real, extra=['--skip', 'visual'])
    check('پروژه‌ی واقعی (حالتِ خودکار) ایرادی نمی‌گیرد',
          rep['counts']['fail'] == 0,
          str([r['msg'][:60] for r in rep['results'] if r['level'] == 'fail'][:3]))
    check('پروژه‌ی واقعی هشدارِ زیادی نمی‌گیرد (≤ ۸)',
          rep['counts']['warn'] <= 8,
          str([r['msg'][:60] for r in rep['results'] if r['level'] == 'warn']))

SPECIAL = [('coverage', t_coverage), ('visual', t_visual_change), ('visual', t_visual_stable), ('visual', t_visual_clock),
           ('visual', t_visual_clock_unmasked), ('regression', t_regression_fixed),
           ('regression', t_regression_broke), ('cli', t_cli), ('cli', t_missing_node), ('cli', t_no_config_leak),
           ('real', t_real_project)]

def main():
    want = set(sys.argv[1:])
    shutil.rmtree(TMP, ignore_errors=True); os.makedirs(TMP, exist_ok=True)
    t0 = time.time()
    print("\n" + "═" * 52 + "\n  تستِ خودِ بازرس\n" + "═" * 52)
    print("\n━━━ نمونه‌های باگ‌دار و سالم ━━━")
    for c in CASES:
        if want and c['id'] not in want: continue
        try: run_case(c)
        except Exception as ex: check(c['name'], False, "💥 " + str(ex)[:200])
    print("\n━━━ رگرسیون، تصویری و خطِ فرمان ━━━")
    for tid, fn in SPECIAL:
        if want and tid not in want: continue
        try: fn()
        except Exception as ex: check(fn.__name__, False, "💥 " + str(ex)[:200])
    print("\n" + "═" * 52)
    print("  %d تست پاس شد در %.0f ثانیه" % (len(PASSED), time.time() - t0))
    if FAILED:
        print("  ❌ %d تست افتاد:" % len(FAILED))
        for f in FAILED: print("     • " + f)
        return 1
    print("  ✅ خودِ بازرس سالم است")
    return 0

if __name__ == '__main__':
    sys.exit(main())
