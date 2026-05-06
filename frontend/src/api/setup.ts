// First-run setup wizard API.
//
// The /setup/status endpoint is anonymous; everything else requires
// the JWT minted by step 1 (POST /setup/admin). Once acquired, the JWT
// is stored in localStorage like a normal login so the rest of the
// wizard authenticates seamlessly.

const API = '/api/v1/setup';

export const SETUP_STEPS = [
  'admin',
  'tls',
  'family',
  'voice',
  'llm',
  'integrations',
  'google_cloud',
  'feature_flags',
] as const;

export type SetupStep = (typeof SETUP_STEPS)[number];


export interface SetupStatus {
  completed: boolean;
  current_step: SetupStep | 'complete';
  version: number;
  completed_steps: SetupStep[];
  has_admin: boolean;
  needs_restart: boolean;
  steps: SetupStep[];
}


// Anonymous — used to decide whether to show the wizard at all.
export async function getSetupStatus(): Promise<SetupStatus> {
  const r = await fetch(`${API}/status`);
  if (!r.ok) throw new Error(`status: ${r.status}`);
  return r.json();
}


export interface AdminCreateRequest {
  email: string;
  password: string;
  full_name: string;
  birth_date?: string;
  timezone?: string;
}


export interface AdminCreateResponse {
  access_token: string;
  refresh_token: string;
  user_id: number;
  email: string;
}


export async function createAdmin(body: AdminCreateRequest): Promise<AdminCreateResponse> {
  const r = await fetch(`${API}/admin`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.json().then((j) => j.detail).catch(() => `HTTP ${r.status}`);
    throw new Error(detail);
  }
  return r.json();
}


// All endpoints below require the admin JWT (already in localStorage
// via auth.ts after step 1).
import { authFetch } from './auth';


function buildPost<TIn, TOut = unknown>(path: string) {
  return async (body: TIn): Promise<TOut> => {
    const r = await authFetch(`${API}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
    });
    if (!r.ok) {
      const detail = await r.json().then((j) => j.detail).catch(() => `HTTP ${r.status}`);
      throw new Error(detail);
    }
    if (r.status === 204) return undefined as TOut;
    return r.json();
  };
}


export const regenerateCert = buildPost<
  { extra_hosts?: string[] },
  { fingerprint_sha256: string; san: string[]; expires_at: string; ca_url: string }
>('/cert/regenerate');
export const skipCert = buildPost<Record<string, never>>('/cert/skip');

export const saveFamily = buildPost<{
  family_name: string;
  glossary: string[];
  family_size: number;
  language: string;
}>('/family');

export const saveVoice = buildPost<{
  voice_name?: string | null;
  voice_rate?: number | null;
  voice_pitch?: number | null;
  voice_volume?: number | null;
  wake_word_enabled?: boolean;
  tts_streaming_enabled?: boolean;
}>('/voice');

export const saveLLM = buildPost<{
  quality_mode: 'fast' | 'quality';
  tone_preset: 'default' | 'privacy' | 'playful';
  max_new_tokens: number;
  system_prompt?: string | null;
  validation_enabled: boolean;
  cognitive_mode: boolean;
}>('/llm');

export const testHomeAssistant = buildPost<
  { url: string; token: string },
  { ok: boolean; entity_count: number }
>('/homeassistant/test');

export const saveHomeAssistant = buildPost<{
  enabled: boolean;
  url: string;
  token?: string | null;
}>('/homeassistant');

export const generateVapid = buildPost<
  { subject?: string },
  { public_key: string; private_key_set: boolean }
>('/vapid/generate');

export const saveTelegram = buildPost<{
  enabled: boolean;
  bot_token?: string | null;
  allowed_chat_ids: string[];
}>('/telegram');

export const completeIntegrations = buildPost<Record<string, never>>('/integrations/complete');

export const saveGoogle = buildPost<{
  client_id?: string | null;
  client_secret?: string | null;
  generate_encryption_key?: boolean;
}>('/google');

export const testCloud = buildPost<
  { api_key: string },
  { ok: boolean; input_tokens: number }
>('/cloud/test');

export const saveCloud = buildPost<{
  enabled: boolean;
  api_key?: string | null;
  skill_author_enabled?: boolean;
}>('/cloud');

export const saveFeatureFlags = buildPost<{
  internet_enabled: boolean;
  news_enabled: boolean;
  radio_enabled: boolean;
  cda_enabled: boolean;
  cda_safe_search_for_minors: boolean;
  proactive_suggestions_enabled: boolean;
  habit_learning_enabled: boolean;
  skill_dispatcher_tier2_enabled: boolean;
  skill_dispatcher_tier3_enabled: boolean;
  voice_recognition_enabled: boolean;
}>('/feature-flags');

export const completeSetup = buildPost<
  Record<string, never>,
  { ok: boolean; needs_restart: boolean }
>('/complete');

export const resetSetup = buildPost<Record<string, never>>('/reset');
