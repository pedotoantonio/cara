import { authFetch } from './auth';

export interface VoiceConfig {
  name: string | null;
  rate: number | null;
  pitch: number | null;
  volume: number | null;
}

export async function getVoiceConfig(): Promise<VoiceConfig> {
  const r = await authFetch('/api/v1/voice/config');
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
