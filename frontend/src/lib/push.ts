// Web Push subscription manager — encapsulates SW + PushManager so
// the rest of the app talks to one tiny API.
//
// Flow:
//   ensurePushReady()         → returns capabilities (browser + backend keys)
//   getCurrentSubscription()  → existing PushSubscription or null
//   enablePush()              → request permission → subscribe → POST to backend
//   disablePush()             → unsubscribe locally + DELETE on backend

import {
  getPushPublicKey,
  subscribePush,
  unsubscribePush,
} from '../api/push';

export interface PushReady {
  supported: boolean;
  configured: boolean; // backend has VAPID keys
  permission: NotificationPermission | 'unsupported';
}

function urlBase64ToUint8Array(base64String: string): BufferSource {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  // Allocate a fresh ArrayBuffer (not SharedArrayBuffer) so the type
  // checker is happy. PushManager requires BufferSource backed by ArrayBuffer.
  const buffer = new ArrayBuffer(raw.length);
  const view = new Uint8Array(buffer);
  for (let i = 0; i < raw.length; i++) view[i] = raw.charCodeAt(i);
  return view;
}

function arrayBufferToBase64Url(buffer: ArrayBuffer | null): string {
  if (!buffer) return '';
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function isPushSupported(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  );
}

export async function ensurePushReady(): Promise<PushReady> {
  if (!isPushSupported()) {
    return { supported: false, configured: false, permission: 'unsupported' };
  }
  let configured = false;
  try {
    const pub = await getPushPublicKey();
    configured = pub.configured;
  } catch {
    configured = false;
  }
  return {
    supported: true,
    configured,
    permission: Notification.permission,
  };
}

export async function getCurrentSubscription(): Promise<PushSubscription | null> {
  if (!isPushSupported()) return null;
  const reg = await navigator.serviceWorker.ready;
  return await reg.pushManager.getSubscription();
}

export async function enablePush(): Promise<{ ok: boolean; reason?: string }> {
  if (!isPushSupported()) {
    return { ok: false, reason: 'Browser non supportato.' };
  }
  // 1) backend must have VAPID keys
  const pub = await getPushPublicKey();
  if (!pub.configured || !pub.public_key) {
    return { ok: false, reason: 'Push non configurato sul server.' };
  }

  // 2) request notification permission (must be triggered by user gesture)
  const perm = await Notification.requestPermission();
  if (perm !== 'granted') {
    return { ok: false, reason: 'Permesso negato.' };
  }

  // 3) ensure SW is installed and ready
  const reg = await navigator.serviceWorker.ready;

  // 4) subscribe via PushManager
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    try {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(pub.public_key),
      });
    } catch (err) {
      console.error('push subscribe failed', err);
      return { ok: false, reason: 'Iscrizione al servizio Push fallita.' };
    }
  }

  // 5) ship to backend
  try {
    const json = sub.toJSON() as PushSubscriptionJSON;
    if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
      return { ok: false, reason: 'Subscription incompleta.' };
    }
    await subscribePush({
      endpoint: json.endpoint,
      keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
      user_agent: navigator.userAgent.slice(0, 240),
    });
    return { ok: true };
  } catch (err) {
    console.error('backend subscribe failed', err);
    // Try to roll back the local subscription so we don't end up with a
    // PushManager subscription the backend doesn't know about.
    try { await sub?.unsubscribe(); } catch {/* ignore */}
    return { ok: false, reason: 'Salvataggio sul server fallito.' };
  }
}

export async function disablePush(): Promise<{ ok: boolean }> {
  const sub = await getCurrentSubscription();
  if (!sub) return { ok: true };
  const endpoint = sub.endpoint;
  try {
    await unsubscribePush(endpoint);
  } catch {/* server-side cleanup best effort */}
  try {
    await sub.unsubscribe();
  } catch {/* may already be gone */}
  return { ok: true };
}

// Re-affirm subscription on app load: if the user has notifications
// permitted AND the local PushManager has a subscription, re-POST it
// to the backend (handles the case where the row was lost or the user
// switched devices). Cheap; idempotent on the backend.
export async function reaffirmSubscriptionSilently(): Promise<void> {
  if (!isPushSupported()) return;
  if (Notification.permission !== 'granted') return;
  try {
    const sub = await getCurrentSubscription();
    if (!sub) return;
    const json = sub.toJSON() as PushSubscriptionJSON;
    if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) return;
    await subscribePush({
      endpoint: json.endpoint,
      keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
      user_agent: navigator.userAgent.slice(0, 240),
    });
  } catch {/* silent */}
}

// Ensure the dummy fns are referenced so Vite doesn't tree-shake the
// b64u helper if a future refactor removes the only call site.
export const __debug = { arrayBufferToBase64Url };
