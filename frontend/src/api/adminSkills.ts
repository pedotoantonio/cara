// Skill Factory admin API — list/get/patch/approve/reject/delete + primitive catalog.
import { authFetch } from './auth';

const API = '/api/v1/admin/skills';

export interface Skill {
  id: string;
  name: string;
  description: string;
  intent_examples: string[];
  slot_extraction: Record<string, unknown>;
  plan: { steps: SkillStep[]; [k: string]: unknown };
  response_template: string | null;
  fallback_response: string | null;
  status: 'pending' | 'active' | 'disabled';
  auto_authored: boolean;
  version: number;
  created_by_user_id: number | null;
  approved_by_user_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface SkillStep {
  id: string;
  tool: string;
  args: Record<string, unknown>;
}

export interface PrimitiveSpec {
  name: string;
  description: string;
  args_schema: Record<string, string>;
  returns_schema: Record<string, string>;
  needs_session: boolean;
  needs_user_id: boolean;
}

export interface SkillPatch {
  description?: string;
  intent_examples?: string[];
  slot_extraction?: Record<string, unknown>;
  plan?: { steps: SkillStep[]; [k: string]: unknown };
  response_template?: string | null;
  fallback_response?: string | null;
}

export async function listSkills(statusFilter?: Skill['status']): Promise<Skill[]> {
  const url = statusFilter ? `${API}?status_filter=${statusFilter}` : API;
  const r = await authFetch(url);
  if (!r.ok) throw new Error(`list skills: ${r.status}`);
  return r.json();
}

export async function getSkill(id: string): Promise<Skill> {
  const r = await authFetch(`${API}/${id}`);
  if (!r.ok) throw new Error(`get skill: ${r.status}`);
  return r.json();
}

export async function patchSkill(id: string, patch: SkillPatch): Promise<Skill> {
  const r = await authFetch(`${API}/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!r.ok) {
    const detail = await r.json().then((j) => j.detail).catch(() => `HTTP ${r.status}`);
    throw new Error(detail);
  }
  return r.json();
}

export async function approveSkill(id: string): Promise<Skill> {
  const r = await authFetch(`${API}/${id}/approve`, { method: 'POST' });
  if (!r.ok) throw new Error(`approve: ${r.status}`);
  return r.json();
}

export async function rejectSkill(id: string): Promise<Skill> {
  const r = await authFetch(`${API}/${id}/reject`, { method: 'POST' });
  if (!r.ok) throw new Error(`reject: ${r.status}`);
  return r.json();
}

export async function deleteSkill(id: string): Promise<void> {
  const r = await authFetch(`${API}/${id}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`delete: ${r.status}`);
}

export async function listPrimitives(): Promise<PrimitiveSpec[]> {
  const r = await authFetch(`${API}/primitives/catalog`);
  if (!r.ok) throw new Error(`primitives: ${r.status}`);
  return r.json();
}
