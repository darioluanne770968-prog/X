// X Daily Digest Service Worker
const CACHE_NAME = 'x-digest-v1';
const OFFLINE_URL = '/offline.html';

// 需要缓存的资源
const PRECACHE_URLS = [
  '/',
  '/offline.html',
  '/static/manifest.json',
  'https://cdn.tailwindcss.com'
];

// 安装事件 - 预缓存资源
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Caching app shell');
        return cache.addAll(PRECACHE_URLS);
      })
      .then(() => self.skipWaiting())
  );
});

// 激活事件 - 清理旧缓存
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames
          .filter(cacheName => cacheName !== CACHE_NAME)
          .map(cacheName => caches.delete(cacheName))
      );
    }).then(() => self.clients.claim())
  );
});

// 请求拦截
self.addEventListener('fetch', event => {
  // 只处理 GET 请求
  if (event.request.method !== 'GET') {
    return;
  }

  // API 请求不缓存
  if (event.request.url.includes('/api/')) {
    event.respondWith(
      fetch(event.request)
        .catch(() => new Response(JSON.stringify({ error: 'Offline' }), {
          headers: { 'Content-Type': 'application/json' }
        }))
    );
    return;
  }

  // 页面请求 - 网络优先，失败时使用缓存
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          // 缓存成功的响应
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, responseClone);
          });
          return response;
        })
        .catch(() => {
          return caches.match(event.request)
            .then(cachedResponse => {
              if (cachedResponse) {
                return cachedResponse;
              }
              return caches.match(OFFLINE_URL);
            });
        })
    );
    return;
  }

  // 静态资源 - 缓存优先
  event.respondWith(
    caches.match(event.request)
      .then(cachedResponse => {
        if (cachedResponse) {
          // 后台更新缓存
          fetch(event.request).then(response => {
            caches.open(CACHE_NAME).then(cache => {
              cache.put(event.request, response);
            });
          });
          return cachedResponse;
        }

        return fetch(event.request).then(response => {
          // 缓存新资源
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, responseClone);
          });
          return response;
        });
      })
  );
});

// 推送通知
self.addEventListener('push', event => {
  const data = event.data ? event.data.json() : {};
  const title = data.title || 'X Daily Digest';
  const options = {
    body: data.body || '新的摘要已生成',
    icon: '/static/icon-192.png',
    badge: '/static/badge-72.png',
    tag: 'digest-notification',
    data: data.url || '/',
    actions: [
      { action: 'view', title: '查看' },
      { action: 'dismiss', title: '忽略' }
    ]
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

// 通知点击
self.addEventListener('notificationclick', event => {
  event.notification.close();

  if (event.action === 'dismiss') {
    return;
  }

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(clientList => {
        // 如果已有窗口，聚焦它
        for (const client of clientList) {
          if (client.url === event.notification.data && 'focus' in client) {
            return client.focus();
          }
        }
        // 否则打开新窗口
        if (clients.openWindow) {
          return clients.openWindow(event.notification.data);
        }
      })
  );
});

// 后台同步
self.addEventListener('sync', event => {
  if (event.tag === 'sync-digest') {
    event.waitUntil(
      fetch('/api/digest/generate', { method: 'POST' })
        .then(response => {
          if (response.ok) {
            self.registration.showNotification('X Daily Digest', {
              body: '摘要已在后台生成',
              icon: '/static/icon-192.png'
            });
          }
        })
    );
  }
});
