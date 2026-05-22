/// <reference lib="webworker" />
// CARA PWA v2 — service worker (injectManifest).
// Strategy:
//   /api/*                 → NetworkOnly (no cache)
//   /_assets/*, /icons/*   → CacheFirst (immutable hashed)
//   /                      → NetworkFirst (no stale HTML after rebuild)
//
// Push handler con rich notifications (image, actions, tag dedup).

import { cleanupOutdatedCaches, precacheAndRoute } from 'workbox-precaching';
import { registerRoute } from 'workbox-routing';
import { NetworkOnly, CacheFirst, NetworkFirst } from 'workbox-strategies';

declare const self: ServiceWorkerGlobalScope;

precacheAndRoute(self.__WB_MANIFEST ?? []);
cleanupOutdatedCaches();

// SKIP_WAITING + claim
self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') void self.skipWaiting();
});
self.addEventListener('install', () => void self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

// API never cached
registerRoute(({ url }) => url.pathname.startsWith('/api/'), new NetworkOnly());

// HTML pages: network-first so new build is picked up immediately
registerRoute(
  ({ request }) => request.mode === 'navigate',
  new NetworkFirst({
    cacheName: 'pages',
    networkTimeoutSeconds: 4,
  }),
);

// Icons + static assets
registerRoute(
  ({ url }) => url.pathname.startsWith('/icons/') || url.pathname.startsWith('/_assets/'),
  new CacheFirst({ cacheName: 'static' }),
);

// PUSH — rich notification
self.addEventListener('push', (event) => {
  let payload: {
    title: string;
    body?: string;
    tag?: string;
    url?: string;
    icon?: string;
    badge?: string;
    image?: string;
    actions?: { action: string; title: string }[];
  } = { title: 'CARA' };
  try {
    if (event.data) payload = { ...payload, ...event.data.json() };
  } catch {
    /* noop */
  }
  // NotificationOptions in lib.dom.d.ts is conservative; cast to include
  // `image` + `actions` (well-supported in modern browsers).
  const options: NotificationOptions & { image?: string; actions?: unknown } = {
    body: payload.body,
    tag: payload.tag,
    icon: payload.icon ?? '/icons/cara-192.png',
    badge: payload.badge ?? '/icons/cara-192.png',
    image: payload.image,
    data: { url: payload.url ?? '/' },
    actions: payload.actions,
  };
  event.waitUntil(self.registration.showNotification(payload.title, options as NotificationOptions));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    (async () => {
      const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const client of all) {
        if (client.url.includes(url) && 'focus' in client) {
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    })(),
  );
});
