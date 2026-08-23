/* مدلند قشم — سرویس‌ورکر
   کارش یه چیزه: فایلِ برنامه رو تو گوشی نگه داره تا هر بار از سرور دانلود نشه.
   هر بار که نسخه‌ی جدید می‌دم، CACHE پایین عوض می‌شه و مرورگر خودش می‌فهمه.
   عمداً skipWaiting نداریم: نسخه‌ی جدید صبر می‌کنه تا خودِ کاربر تأیید کنه. */
const CACHE = 'mlq-2026-08-23-80';
const CORE = ['./', './index.html', './h2c.js', './manifest.json',
  './font1.woff2', './font2.woff2',
  './img1.png', './img2.png', './img3.png', './img4.png',
  './icon-192.png', './icon-512.png'];

self.addEventListener('install', (e) => {
  // تک‌تک کش می‌کنیم: اگر یک فایل نبود، کلِ نصب شکست نخورد
  e.waitUntil(caches.open(CACHE).then((c) =>
    Promise.all(CORE.map((u) => c.add(u).catch(() => {})))
  ).catch(() => {}));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// صفحه می‌گه «برو رو نسخه‌ی جدید»
self.addEventListener('message', (e) => {
  if (e.data === 'skipWaiting') self.skipWaiting();
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  let url;
  try { url = new URL(req.url); } catch (_) { return; }

  // فقط فایل‌های خودمون. سوپابیس و بقیه هیچ‌وقت کش نمی‌شن —
  // وگرنه فاکتور و موجودیِ بیات نشونت می‌داد.
  if (url.origin !== self.location.origin) return;
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return;

  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(req, { ignoreSearch: true });

    const net = fetch(req).then((res) => {
      if (res && res.ok && res.type === 'basic') {
        cache.put(req, res.clone()).catch(() => {});
      }
      return res;
    }).catch(() => null);

    // اول از گوشی بده (فوری)، بعد پشتِ صحنه تازه‌ش کن
    if (hit) { e.waitUntil(net); return hit; }

    const res = await net;
    if (res) return res;
    const shell = await cache.match('./index.html', { ignoreSearch: true });
    return shell || new Response('آفلاین', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
  })());
});
