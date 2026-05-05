// Admin memory governance — list users + their facts + purge.
import { authFetch } from './auth';
import type { Fact } from './memory';

const API = '/api/v1/admin/memory';

export interface UserMemorySummary {
  user_id: number;
  email: string;
  full_name: string | null;
  role: string | null;
  facts_total: number;
  facts_active: number;
}

export async function listUsersWithFacts(): Promise<UserMemorySummary[]> {
  const r = await authFetch(`${API}/users`);
  if (!r.ok) throw new Error(`users: ${r.status}`);
  return r.json();
}

export async function listUserFacts(
  userId: number,
  opts: { activeOnly?: boolean } = {},
): Promise<Fact[]> {
  const p = new URLSearchParams();
  p.set('active_only', String(opts.activeOnly ?? false));
  const r = await authFetch(`${API}/${userId}/facts?${p.toString()}`);
  if (!r.ok) throw new Error(`user facts: ${r.status}`);
  return r.json();
}

export async function deactivateUserFact(userId: number, factId: number): Promise<void> {
  const r = await authFetch(`${API}/${userId}/facts/${factId}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`deactivate: ${r.status}`);
}

export async function purgeUserMemory(userId: number): Promise<{ deleted: number }> {
  const r = await authFetch(`${API}/${userId}/purge`, { method: 'POST' });
  if (!r.ok) throw new Error(`purge: ${r.status}`);
  return r.json();
}
