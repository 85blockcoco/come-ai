const CACHE = 'nage-shell-v1';
const SHELL = ['/app-static/', '/app-static/index.html', '/app-static/app.css?v=20261103-vc-review-4&build=immersive-4', '/app-static/app.js?v=20261103-vc-review-4&build=immersive-4', '/app-static/icon.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/career')) {
    if (url.pathname.startsWith('/career/summary/')) {
      e.respondWith(fetch(e.request).then((response) => {
        const copy = response.clone();
        return caches.open(CACHE).then((cache) => cache.put(e.request, copy)).then(() => response);
      }).catch(() => caches.match(e.request)));
      return;
    }
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
