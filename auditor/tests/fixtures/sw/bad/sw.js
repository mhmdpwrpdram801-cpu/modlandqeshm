self.addEventListener('install', e => {
  e.waitUntil(caches.open('v1').then(c => c.addAll(['./index.html','./app.js','./missing.js'])));
});
