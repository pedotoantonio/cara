import { authFetch } from './auth';

const API = '/api/v1';

export interface PersonAtHome {
  name: string;
  last_seen: string;     // ISO timestamp
  minutes_ago: number;
}

export interface PresenceResponse {
  window_minutes: number;
  count: number;
  people: PersonAtHome[];
}

export async function whoIsHome(windowMinutes = 15): Promise<PresenceResponse> {
  const r = await authFetch(`${API}/family/who-is-home?window_minutes=${windowMinutes}`);
  if (!r.ok) {
    if (r.status === 503) throw new Error('Riconoscimento facciale non disponibile');
    throw new Error(`HTTP ${r.status}`);
  }
  return r.json();
}
