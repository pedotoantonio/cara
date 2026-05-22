import { apiGet, apiPost, authFetch } from './client';

export interface GoogleStatus {
  connected: boolean;
  email?: string | null;
  scopes?: string[];
  last_sync_at?: string | null;
  calendar_enabled?: boolean;
  gmail_enabled?: boolean;
}

export async function getGoogleStatus(): Promise<GoogleStatus> {
  try {
    return await apiGet<GoogleStatus>('/integrations/google/status');
  } catch {
    return { connected: false };
  }
}

export async function startGoogleOAuth(): Promise<{ url?: string }> {
  try {
    return await apiGet<{ url?: string }>('/oauth/google/start');
  } catch {
    return {};
  }
}

export async function disconnectGoogle(): Promise<void> {
  const r = await authFetch('/integrations/google/disconnect', { method: 'POST' });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

export async function syncGoogleNow(): Promise<void> {
  await apiPost('/integrations/google/sync', {}).catch(() => undefined);
}
