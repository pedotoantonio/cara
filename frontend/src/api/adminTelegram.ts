/**
 * Admin client for /api/v1/admin/telegram — chat ↔ user mappings.
 */

import { authFetch } from './auth';

const API = '/api/v1/admin/telegram';

export interface TelegramMapping {
  chat_id: number;
  user_id: number;
  user_email: string;
  label: string | null;
  notifications_enabled: boolean;
  voice_enabled: boolean;
  last_active_at: string | null;
  source: 'db' | 'env';
}

export async function listTelegramMappings(): Promise<TelegramMapping[]> {
  const r = await authFetch(`${API}/mappings`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createTelegramMapping(body: {
  chat_id: number;
  user_email: string;
  label?: string | null;
  notifications_enabled?: boolean;
  voice_enabled?: boolean;
}): Promise<TelegramMapping> {
  const r = await authFetch(`${API}/mappings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json()).detail ?? `HTTP ${r.status}`);
  return r.json();
}

export async function updateTelegramMapping(
  chatId: number,
  patch: {
    label?: string | null;
    notifications_enabled?: boolean;
    voice_enabled?: boolean;
    user_email?: string;
  },
): Promise<TelegramMapping> {
  const r = await authFetch(`${API}/mappings/${chatId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error((await r.json()).detail ?? `HTTP ${r.status}`);
  return r.json();
}

export async function deleteTelegramMapping(chatId: number): Promise<void> {
  const r = await authFetch(`${API}/mappings/${chatId}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

export async function sendTestTelegram(chatId: number, text?: string): Promise<unknown> {
  const r = await authFetch(`${API}/mappings/${chatId}/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: text ?? '🧪 Test da CARA' }),
  });
  if (!r.ok) throw new Error((await r.json()).detail ?? `HTTP ${r.status}`);
  return r.json();
}
