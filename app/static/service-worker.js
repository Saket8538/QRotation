const CACHE_NAME = 'smart-attendance-v2';
const APP_SHELL = ['/', '/student/scan', '/static/manifest.json', '/static/js/offline-attendance.js'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => Promise.all(
    APP_SHELL.map(asset => cache.add(asset).catch(() => null))
  )));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
  )));
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET' || new URL(request.url).origin !== self.location.origin) return;
  // Dynamic attendance, QR, and API responses must always come from the network.
  if (new URL(request.url).pathname.startsWith('/api/') || new URL(request.url).pathname.includes('/scan')) return;
  event.respondWith(
    fetch(request).then(response => {
      const copy = response.clone();
      caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
      return response;
    }).catch(() => caches.match(request).then(cached => cached || caches.match('/')))
  );
});
