import { apiGet } from './client';

export interface PersonaProfile {
  user_id: number;
  markdown: string;
  confidence: number | null;
  last_status: string | null;
  last_built_at: string | null;
}

export async function getMyPersona(): Promise<PersonaProfile | null> {
  try {
    const r = await apiGet<PersonaProfile | null>('/persona/me');
    return r;
  } catch {
    return null;
  }
}
