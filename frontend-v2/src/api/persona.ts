import { apiDelete, apiGet, apiPost } from './client';

export interface PersonaProfile {
  user_id: number;
  markdown: string;
  confidence: number | null;
  sections?: Record<string, { stable: string[]; episodic: { date: string; text: string }[] }> | null;
  last_status: string | null;
  last_error: string | null;
  last_built_at: string | null;
}

export interface RebuildResult {
  status: string;
  chunks_processed?: number;
  messages_consumed?: number;
  confidence?: number | null;
  markdown_chars?: number;
  error?: string | null;
}

export async function getMyPersona(): Promise<PersonaProfile | null> {
  try {
    const r = await apiGet<PersonaProfile | null>('/persona/me');
    return r;
  } catch {
    return null;
  }
}

export async function rebuildMyPersona(): Promise<RebuildResult> {
  return apiPost<RebuildResult>('/persona/me/rebuild', {});
}

export async function deleteMyPersona(): Promise<void> {
  return apiDelete('/persona/me');
}
