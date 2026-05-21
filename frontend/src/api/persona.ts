// Persona profile API client — self-service + admin.
import { authFetch } from './auth';

const API = '/api/v1';

export interface PersonaSection {
  stable: string[];
  episodic: { date: string; text: string }[];
}

export interface PersonaProfile {
  user_id: number;
  markdown: string;
  confidence: number | null;
  sections: Record<string, PersonaSection> | null;
  last_status: string | null;
  last_error: string | null;
  last_built_at: string | null;
  last_message_id_consumed: number | null;
}

export interface RebuildResult {
  status: string;
  chunks_processed?: number;
  messages_consumed?: number;
  confidence?: number | null;
  markdown_chars?: number;
  error?: string | null;
}

// ─── Self-service ──────────────────────────────────────────────────────

export async function getMyPersona(): Promise<PersonaProfile | null> {
  const r = await authFetch(`${API}/persona/me`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`persona/me: HTTP ${r.status}`);
  const data = await r.json();
  // Backend returns `null` body when no profile yet.
  return data && typeof data === 'object' && 'user_id' in data ? (data as PersonaProfile) : null;
}

export async function rebuildMyPersona(): Promise<RebuildResult> {
  const r = await authFetch(`${API}/persona/me/rebuild`, { method: 'POST' });
  if (r.status === 429) {
    const detail = await r.json().then((j) => j.detail).catch(() => 'cooldown');
    throw new Error(detail);
  }
  if (!r.ok) throw new Error(`rebuild: HTTP ${r.status}`);
  return r.json();
}

export async function deleteMyPersona(): Promise<void> {
  const r = await authFetch(`${API}/persona/me`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`delete: HTTP ${r.status}`);
}

// ─── Admin ─────────────────────────────────────────────────────────────

export async function adminGetPersona(userId: number): Promise<PersonaProfile | null> {
  const r = await authFetch(`${API}/admin/persona/${userId}`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`admin persona: HTTP ${r.status}`);
  const data = await r.json();
  return data && typeof data === 'object' && 'user_id' in data ? (data as PersonaProfile) : null;
}

export async function adminPatchPersona(
  userId: number,
  body: { markdown: string; confidence?: number | null },
): Promise<PersonaProfile> {
  const r = await authFetch(`${API}/admin/persona/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`patch: HTTP ${r.status}`);
  return r.json();
}

export async function adminRebuildPersona(userId: number): Promise<RebuildResult> {
  const r = await authFetch(`${API}/admin/persona/${userId}/rebuild`, { method: 'POST' });
  if (!r.ok) throw new Error(`rebuild: HTTP ${r.status}`);
  return r.json();
}

export async function adminDeletePersona(userId: number): Promise<void> {
  const r = await authFetch(`${API}/admin/persona/${userId}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`delete: HTTP ${r.status}`);
}
