// Web Push subscribe / unsubscribe / test API client.

import { authFetch } from './auth';

const API = '/api/v1';

export interface PushPublicKey {
  public_key: string | null;
  configured: boolean;
}

export async function getPushPublicKey(): Promise<PushPublicKey> {
  const r = await fetch(`${API}/push/public-key`);
  if (!r.ok) throw new Error(`public-key: ${r.status}`);
  return r.json();
}

interface SubscribeBody {
  endpoint: string;
  keys: { p256dh: string; auth: string };
  user_agent?: string;
}

export async function subscribePush(body: SubscribeBody): Promise<void> {
  const r = await authFetch(`${API}/push/subscribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`subscribe: ${r.status}`);
}

export async function unsubscribePush(endpoint: string): Promise<void> {
  const r = await authFetch(`${API}/push/subscribe`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoint }),
  });
  if (!r.ok && r.status !== 204) throw new Error(`unsubscribe: ${r.status}`);
}

export async function sendTestPush(): Promise<{ delivered: number }> {
  const r = await authFetch(`${API}/push/test`, { method: 'POST' });
  if (!r.ok) throw new Error(`test: ${r.status}`);
  return r.json();
}
