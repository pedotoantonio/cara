// Admin proactivity API client.
import { authFetch } from './auth';

const API = '/api/v1/admin/proactivity';

export interface RuleInfo {
  rule_id: string;
  description: string;
  enabled: boolean;
  cooldown_hours: number;
  last_fired_at: string | null;
}

export interface SuggestionPreview {
  rule_id: string;
  text: string;
  priority: number;
  target_user_id: number | null;
  action: Record<string, unknown> | null;
}

export async function listRules(): Promise<RuleInfo[]> {
  const r = await authFetch(`${API}/rules`);
  if (!r.ok) throw new Error(`rules: ${r.status}`);
  return r.json();
}

export async function toggleRule(ruleId: string, enabled: boolean): Promise<void> {
  const p = new URLSearchParams({ enabled: String(enabled) });
  const r = await authFetch(`${API}/rules/${encodeURIComponent(ruleId)}/toggle?${p}`, {
    method: 'POST',
  });
  if (!r.ok) throw new Error(`toggle: ${r.status}`);
}

export async function runNow(): Promise<{ suggestions: SuggestionPreview[]; count: number }> {
  const r = await authFetch(`${API}/run-now`, { method: 'POST' });
  if (!r.ok) throw new Error(`run-now: ${r.status}`);
  return r.json();
}
