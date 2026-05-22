// Web Push (VAPID) — subscribe + reaffirm + unsubscribe.

import { apiGet, apiPost, authFetch } from './client';

interface PublicKeyResp {
  configured: boolean;
  public_key: string | null;
}

export async function getPushPublicKey(): Promise<PublicKeyResp> {
  try {
    return await apiGet<PublicKeyResp>('/push/public-key');
  } catch {
    return { configured: false, public_key: null };
  }
}

function urlBase64ToUint8Array(b64: string): Uint8Array {
  const padding = '='.repeat((4 - (b64.length % 4)) % 4);
  const base64 = (b64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = window.atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export interface PushSetupResult {
  status: 'subscribed' | 'unsupported' | 'denied' | 'no-key' | 'error';
  detail?: string;
}

export async function setupPushSubscription(label = 'browser'): Promise<PushSetupResult> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    return { status: 'unsupported' };
  }
  if (!('Notification' in window)) return { status: 'unsupported' };
  if (Notification.permission === 'denied') {
    return { status: 'denied' };
  }
  const { public_key, configured } = await getPushPublicKey();
  if (!configured || !public_key) return { status: 'no-key' };

  try {
    const reg = await navigator.serviceWorker.ready;
    const existing = await reg.pushManager.getSubscription();
    const sub =
      existing ??
      (await reg.pushManager.subscribe({
        userVisibleOnly: true,
        // TS 5.6 PushSubscriptionOptionsInit type is too strict — cast.
        applicationServerKey: urlBase64ToUint8Array(public_key).buffer as ArrayBuffer,
      }));
    await apiPost('/push/subscribe', {
      endpoint: sub.endpoint,
      keys: sub.toJSON().keys,
      user_agent: navigator.userAgent.slice(0, 200),
      label,
    });
    return { status: 'subscribed' };
  } catch (err) {
    return { status: 'error', detail: (err as Error).message };
  }
}

export async function unsubscribePush(): Promise<void> {
  if (!('serviceWorker' in navigator)) return;
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await sub.unsubscribe();
      await authFetch('/push/subscribe', { method: 'DELETE' });
    }
  } catch {
    /* noop */
  }
}

/**
 * Reaffirm — chiama al boot dell'app. Se permission granted ma
 * subscription locale persa, ri-subscribe silenziosamente.
 */
export async function reaffirmSubscriptionSilently(): Promise<void> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
  if (Notification.permission !== 'granted') return;
  try {
    const reg = await navigator.serviceWorker.ready;
    const existing = await reg.pushManager.getSubscription();
    if (!existing) {
      await setupPushSubscription('auto-reaffirm');
    } else {
      // Just re-POST so backend has fresh user_agent / label
      await apiPost('/push/subscribe', {
        endpoint: existing.endpoint,
        keys: existing.toJSON().keys,
        user_agent: navigator.userAgent.slice(0, 200),
        label: 'auto-reaffirm',
      }).catch(() => undefined);
    }
  } catch {
    /* noop */
  }
}
