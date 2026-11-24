// Service Worker cho OMR Mobile PWA (v8 - Network-First for Navigation)
const CACHE_NAME = 'omr-pwa-v8';
const ASSETS_TO_CACHE = [
  '/scanner',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

// Xử lý fetch request
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Không can thiệp các request không phải GET hoặc các endpoint API
  if (event.request.method !== 'GET' || url.pathname.startsWith('/api/')) {
    return;
  }

  // Đối với request điều hướng (Navigation / Scanner / Trang chủ): Luôn ưu tiên lấy bản mới nhất từ mạng (Network-First)
  const isNavigation = event.request.mode === 'navigate' || url.pathname === '/scanner' || url.pathname === '/';
  if (isNavigation) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response && response.status === 200) {
            const resClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, resClone));
          }
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(event.request);
          if (cached) return cached;
          return caches.match('/scanner');
        })
    );
    return;
  }

  // Đối với các tài nguyên tĩnh khác: Network-First với fallback cache
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response && response.status === 200) {
          const resClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, resClone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
