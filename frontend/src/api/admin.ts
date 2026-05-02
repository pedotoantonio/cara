import { authFetch } from './auth';

const API = '/api/v1';

export type AdminSettings = Record<string, unknown>;

export async function getAdminSettings(): Promise<AdminSettings> {
  const r = await authFetch(`${API}/admin/settings`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function patchAdminSettings(
  settings: Partial<AdminSettings>,
): Promise<AdminSettings> {
  const r = await authFetch(`${API}/admin/settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings }),
  });
  if (!r.ok) {
    const detail = await r.json().then((j) => j.detail).catch(() => `HTTP ${r.status}`);
    throw new Error(detail);
  }
  return r.json();
}

export interface AuditEntry {
  id: string;
  actor_email: string | null;
  action: string;
  target_kind: string | null;
  target_id: string | null;
  detail: Record<string, unknown> | null;
  ip: string | null;
  note: string | null;
  created_at: string;
}

export async function getAdminAudit(limit = 100): Promise<AuditEntry[]> {
  const r = await authFetch(`${API}/admin/audit?limit=${limit}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
