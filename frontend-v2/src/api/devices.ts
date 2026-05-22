import { apiDelete, apiGet, apiPost } from './client';

export interface Device {
  id: number;
  label: string;
  surface: string;
  fingerprint: string;
  paired_at: string;
  last_seen_at?: string | null;
  active: boolean;
  owner_user_id?: number | null;
}

export async function listDevices(): Promise<Device[]> {
  try {
    return await apiGet<Device[]>('/devices');
  } catch {
    return [];
  }
}

export async function pairStart(): Promise<{ code: string; expires_at: string }> {
  return apiPost<{ code: string; expires_at: string }>('/devices/pair-start', {});
}

export async function removeDevice(id: number): Promise<void> {
  return apiDelete(`/devices/${id}`);
}
