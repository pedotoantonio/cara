import { authFetch } from './auth';

const API = '/api/v1';

export interface RadioStation {
  id: string;
  name: string;
  url: string;
  genre: string;
  country: string;
  description: string;
}

export class RadioDisabledError extends Error {}

export async function listStations(): Promise<RadioStation[]> {
  const r = await authFetch(`${API}/radio`);
  if (r.status === 503) throw new RadioDisabledError('Radio disabilitata (admin).');
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getStation(id: string): Promise<RadioStation> {
  const r = await authFetch(`${API}/radio/${encodeURIComponent(id)}`);
  if (r.status === 503) throw new RadioDisabledError('Radio disabilitata (admin).');
  if (r.status === 404) throw new Error(`Stazione '${id}' non trovata`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
