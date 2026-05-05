// Integrations + OAuth + proposals API client.
import { authFetch } from './auth';

const API = '/api/v1';

export interface Integration {
  id: number;
  provider: string;
  scope_set: string;
  account_email: string;
  config: Record<string, unknown>;
  revoked: boolean;
  last_synced_at: string | null;
  created_at: string;
}

export interface GoogleCalendar {
  id: string;
  summary: string;
  primary: boolean;
  access_role: string;
}

export interface OAuthStatus {
  available: boolean;
}

// ---------- OAuth ----------

export async function getOAuthStatus(): Promise<OAuthStatus> {
  const r = await fetch(`${API}/oauth/google/status`);
  if (!r.ok) throw new Error(`oauth status: ${r.status}`);
  return r.json();
}

export async function startGoogleAuth(scopeSet: 'calendar:rw' | 'gmail:ro'): Promise<string> {
  const r = await authFetch(`${API}/oauth/google/authorize?scope_set=${encodeURIComponent(scopeSet)}`, {
    method: 'POST',
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail ?? `authorize: ${r.status}`);
  }
  return (await r.json()).authorize_url;
}

// ---------- Integrations CRUD ----------

export async function listIntegrations(): Promise<Integration[]> {
  const r = await authFetch(`${API}/integrations`);
  if (!r.ok) throw new Error(`integrations: ${r.status}`);
  return r.json();
}

export async function listGoogleCalendars(): Promise<GoogleCalendar[]> {
  const r = await authFetch(`${API}/integrations/calendars`);
  if (!r.ok) throw new Error(`calendars: ${r.status}`);
  return r.json();
}

export async function setIntegrationConfig(
  id: number,
  body: { calendar_id?: string; push_enabled?: boolean },
): Promise<void> {
  const r = await authFetch(`${API}/integrations/${id}/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`config: ${r.status}`);
}

export async function disconnectIntegration(id: number): Promise<void> {
  const r = await authFetch(`${API}/integrations/${id}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`disconnect: ${r.status}`);
}

// ---------- Proposals ----------

export interface Proposal {
  id: number;
  message_id: string;
  from_address: string | null;
  subject: string | null;
  snippet: string | null;
  proposal_type: string;
  proposal_args: {
    title?: string;
    due_date?: string | null;
    location?: string | null;
    person?: string | null;
    notes?: string | null;
  };
  confidence: number;
  source_layer: string;
  status: string;
  created_at: string;
  decided_at: string | null;
}

export async function listProposals(status: 'pending' | 'accepted' | 'rejected' = 'pending'): Promise<Proposal[]> {
  const r = await authFetch(`${API}/proposals?status_filter=${status}&limit=100`);
  if (!r.ok) throw new Error(`proposals: ${r.status}`);
  return r.json();
}

export async function acceptProposal(id: number): Promise<{ task_id: string }> {
  const r = await authFetch(`${API}/proposals/${id}/accept`, { method: 'POST' });
  if (!r.ok) throw new Error(`accept: ${r.status}`);
  return r.json();
}

export async function rejectProposal(id: number): Promise<void> {
  const r = await authFetch(`${API}/proposals/${id}/reject`, { method: 'POST' });
  if (!r.ok) throw new Error(`reject: ${r.status}`);
}
