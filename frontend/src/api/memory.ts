// Memory API client — semantic facts CRUD + GDPR export + purge.
import { authFetch } from './auth';

const API = '/api/v1';

export interface Fact {
  id: number;
  user_id: number | null;
  type: string;
  text: string;
  source: string;
  confidence: number;
  first_seen: string;
  last_confirmed: string;
  expiry: string | null;
  active: boolean;
}

export interface FactCreate {
  text: string;
  type?: string;
  confidence?: number;
}

export interface FactPatch {
  text?: string;
  confidence?: number;
  active?: boolean;
}

export async function listFacts(
  opts: { activeOnly?: boolean; type?: string; limit?: number } = {},
): Promise<Fact[]> {
  const p = new URLSearchParams();
  p.set('active_only', String(opts.activeOnly ?? true));
  if (opts.type) p.set('fact_type', opts.type);
  p.set('limit', String(opts.limit ?? 200));
  const r = await authFetch(`${API}/memory/facts?${p.toString()}`);
  if (!r.ok) throw new Error(`facts list: ${r.status}`);
  return r.json();
}

export async function createFact(body: FactCreate): Promise<Fact> {
  const r = await authFetch(`${API}/memory/facts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`fact create: ${r.status}`);
  return r.json();
}

export async function patchFact(id: number, body: FactPatch): Promise<Fact> {
  const r = await authFetch(`${API}/memory/facts/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`fact patch: ${r.status}`);
  return r.json();
}

export async function deleteFact(id: number): Promise<void> {
  const r = await authFetch(`${API}/memory/facts/${id}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`fact delete: ${r.status}`);
}

export async function exportMyMemory(): Promise<Blob> {
  const r = await authFetch(`${API}/memory/export`);
  if (!r.ok) throw new Error(`export: ${r.status}`);
  // Re-wrap as Blob for download.
  const text = await r.text();
  return new Blob([text], { type: 'application/json' });
}

export async function purgeMyMemory(): Promise<{ deleted: number }> {
  const r = await authFetch(`${API}/memory/purge`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`purge: ${r.status}`);
  return r.json();
}
