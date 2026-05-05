// Device pairing + admin management API.

const API = '/api/v1/devices';

export type SurfaceClass = 'wall' | 'mobile' | 'desktop' | 'watch' | 'tv';
export type DeviceStatus = 'pending' | 'online' | 'offline' | 'disabled' | 'error';

export interface Device {
  id: string;
  friendly_name: string;
  surface_class: SurfaceClass;
  location: string | null;
  status: DeviceStatus;
  enabled: boolean;
  capabilities: Record<string, unknown>;
  paired_at: string;
  last_seen: string | null;
  paired_by_user_id: number | null;
}

export interface PairTicket {
  code: string;
  expires_at: string;
}

export interface PairStatus {
  status: 'waiting' | 'paired' | 'expired';
  device_token: string | null;
  device_id: string | null;
  friendly_name: string | null;
  surface_class: SurfaceClass | null;
}


// ---- Anonymous (used by an unpaired device) -----------------------------


export async function startPair(opts: {
  suggestedName?: string;
  suggestedSurface?: SurfaceClass;
} = {}): Promise<PairTicket> {
  const r = await fetch(`${API}/pair/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      suggested_name: opts.suggestedName ?? null,
      suggested_surface: opts.suggestedSurface ?? null,
    }),
  });
  if (!r.ok) throw new Error(`pair/start: ${r.status}`);
  return r.json();
}


export async function getPairStatus(code: string): Promise<PairStatus> {
  const r = await fetch(`${API}/pair/status?code=${encodeURIComponent(code)}`);
  if (!r.ok) throw new Error(`pair/status: ${r.status}`);
  return r.json();
}


// ---- Admin --------------------------------------------------------------

import { authFetch } from './auth';


export async function finalizePair(input: {
  code: string;
  friendly_name: string;
  surface_class: SurfaceClass;
  location?: string | null;
  capabilities?: Record<string, unknown>;
}): Promise<Device> {
  const r = await authFetch(`${API}/pair/finalize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!r.ok) {
    const detail = await r.json().then((j) => j.detail).catch(() => `HTTP ${r.status}`);
    throw new Error(detail);
  }
  return r.json();
}


export async function listDevices(): Promise<Device[]> {
  const r = await authFetch(API);
  if (!r.ok) throw new Error(`list: ${r.status}`);
  return r.json();
}


export async function patchDevice(
  id: string,
  patch: Partial<Pick<Device, 'friendly_name' | 'surface_class' | 'location' | 'enabled'>>,
): Promise<Device> {
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


export async function deleteDevice(id: string): Promise<void> {
  const r = await authFetch(`${API}/${id}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`delete: ${r.status}`);
}
