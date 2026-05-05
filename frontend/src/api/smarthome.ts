// Smart Home API client.
import { authFetch } from './auth';

const API = '/api/v1/smarthome';

export interface Entity {
  id: string;             // canonical "homeassistant:light.salotto"
  provider: string;
  domain: string;
  friendly_name: string;
  area: string | null;
  state: string | null;
  attributes: Record<string, unknown>;
  capabilities: string[];
}

export interface HealthStatus {
  ok: boolean;
  provider: string;
  detail: string | null;
  last_event_age_s: number | null;
}

export interface Scene {
  id: string;
  friendly_name: string;
  area: string | null;
}

export interface ResolveResult {
  matched_intent: boolean;
  action: string | null;
  target_phrase: string | null;
  value: string | null;
  needs_clarification: boolean;
  reason: string | null;
  candidates: Array<{
    entity_id: string;
    alias: string;
    area: string | null;
    score: number;
    source: string;
  }>;
}

export async function listEntities(): Promise<Entity[]> {
  const r = await authFetch(`${API}/entities`);
  if (!r.ok) throw new Error(`entities: ${r.status}`);
  return r.json();
}

export async function getHealth(): Promise<HealthStatus> {
  const r = await authFetch(`${API}/health`);
  if (!r.ok) throw new Error(`health: ${r.status}`);
  return r.json();
}

export async function listScenes(): Promise<Scene[]> {
  const r = await authFetch(`${API}/scenes`);
  if (!r.ok) throw new Error(`scenes: ${r.status}`);
  return r.json();
}

export async function callService(body: {
  domain: string;
  service: string;
  entity_id: string;
  params?: Record<string, unknown>;
  confirmed?: boolean;
}): Promise<{ executed: boolean; requires_confirmation: boolean; result?: unknown }> {
  const r = await authFetch(`${API}/services`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail ?? `services: ${r.status}`);
  }
  return r.json();
}

export async function resolveUtterance(
  utterance: string,
  presentInArea?: string,
): Promise<ResolveResult> {
  const r = await authFetch(`${API}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ utterance, present_in_area: presentInArea }),
  });
  if (!r.ok) throw new Error(`resolve: ${r.status}`);
  return r.json();
}
