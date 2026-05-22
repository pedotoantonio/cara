import { apiGet, apiPatch, setTokens, clearTokens, ApiError, NetworkError } from './client';

export type FamilyRole = 'parent' | 'teen' | 'child' | 'elder' | 'guest';
export type ToneKey = 'default' | 'calmo' | 'energico' | 'formale' | 'playful';

export const TONE_LABELS: Record<ToneKey, { label: string; description: string }> = {
  default: { label: 'Standard', description: 'Tono caloroso e diretto, quello di base.' },
  calmo: { label: 'Calmo', description: 'Tranquillo e misurato. Frasi brevi, pause naturali.' },
  energico: { label: 'Energico', description: 'Vivace, propulsivo, incoraggiante.' },
  formale: { label: 'Formale', description: 'Uso del "lei", registro educato.' },
  playful: { label: 'Giocoso', description: 'Leggerezza e ironia gentile.' },
};

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  is_admin: boolean;
  is_active: boolean;
  role: FamilyRole;
  birth_date: string | null;
  tone_preference: ToneKey | null;
  created_at: string;
}

interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

/**
 * Try password-less LAN login. Returns true if backend issued tokens
 * (we're on home WiFi or WireGuard VPN). False otherwise.
 */
export async function tryLanLogin(): Promise<boolean> {
  try {
    const r = await fetch('/api/v1/auth/lan-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    if (!r.ok) return false;
    const data = (await r.json()) as TokenPair;
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

export async function login(email: string, password: string): Promise<void> {
  const r = await fetch('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) {
    const detail = await r
      .json()
      .then((j) => j.detail ?? `HTTP ${r.status}`)
      .catch(() => `HTTP ${r.status}`);
    throw new Error(String(detail));
  }
  const data = (await r.json()) as TokenPair;
  setTokens(data.access_token, data.refresh_token);
}

export function logout() {
  clearTokens();
}

export async function fetchMe(): Promise<User> {
  return apiGet<User>('/auth/me');
}

export async function updateMe(patch: {
  full_name?: string | null;
  birth_date?: string | null;
  tone_preference?: ToneKey | null;
  role?: FamilyRole | null;
}): Promise<User> {
  return apiPatch<User>('/auth/me', patch);
}

export { ApiError, NetworkError };
