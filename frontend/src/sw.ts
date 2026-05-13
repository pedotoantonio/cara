/// <reference lib="webworker" />
// Custom service worker — Workbox precache + Web Push handler.
//
// Uses `injectManifest` mode (vite-plugin-pwa). The plugin replaces
// `self.__WB_MANIFEST` with the precache list at build time. Anything
// else in this file is ours to control.

import { precacheAndRoute, cleanupOutdatedCaches } from 'workbox-precaching';
import { setDefaultHandler, registerRoute } from 'workbox-routing';
import { CacheFirst, NetworkOnly } from 'workbox-strategies';

declare let self: ServiceWorkerGlobalScope;

// ── Precache the build manifest ────────────────────────────
cleanupOutdatedCaches();
precacheAndRoute(self.__WB_MANIFEST);

// /api/* must NEVER be cached — would break SSE chat + auth.
registerRoute(
  ({ url }) => url.pathname.startsWith('/api/'),
  new NetworkOnly(),
);

// face-api.js weights (≈7 MB total): cache-first, runtime. Not in the
// precache manifest because (a) they're heavy and shouldn't block first
// install, (b) they're only fetched when the user enables face
// recognition. Versioning is implicit: the URL includes the file name
// and the build redeploys to a new path if the model bundle changes.
registerRoute(
  ({ url }) => url.pathname.startsWith('/models/face-api/'),
  new CacheFirst({
    cacheName: 'face-api-models-v1',
  }),
);

setDefaultHandler(new NetworkOnly());

// ── Web Push handler ───────────────────────────────────────
//
// Backend sends a JSON payload `{title, body, tag, url, icon, badge}`.
// We render it as a native notification with a tag so a re-pushed
// reminder for the same task replaces the previous one rather than
// stacking three on the user's lock screen.

interface PushPayload {
  title: string;
  body: string;
  tag?: string;
  url?: string;
  icon?: string;
  badge?: string;
}

function parsePush(event: PushEvent): PushPayload {
  if (!event.data) {
    return { title: 'Cara', body: 'Hai un nuovo promemoria.' };
  }
  try {
    return event.data.json() as PushPayload;
  } catch {
    return { title: 'Cara', body: event.data.text() };
  }
}

self.addEventListener('push', (event) => {
  const data = parsePush(event);
  const opts: NotificationOptions = {
    body: data.body,
    tag: data.tag ?? 'cara',
    icon: data.icon ?? '/icon-192.png',
    badge: data.badge ?? '/icon-192.png',
    data: { url: data.url ?? '/' },
    requireInteraction: false,
    silent: false,
  };
  event.waitUntil(self.registration.showNotification(data.title, opts));
});

// Click → focus existing tab if open, else open `url`.
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data?.url as string) || '/';
  event.waitUntil(
    self.clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then((clients) => {
        for (const client of clients) {
          if ('focus' in client && client.url.endsWith(target)) {
            return (client as WindowClient).focus();
          }
        }
        for (const client of clients) {
          if ('navigate' in client) {
            (client as WindowClient).navigate(target).catch(() => undefined);
            return (client as WindowClient).focus();
          }
        }
        return self.clients.openWindow(target);
      }),
  );
});

// Allow page code to force-update the SW immediately on deploy.
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
