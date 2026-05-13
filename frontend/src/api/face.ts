/**
 * Face recognition REST client.
 *
 * Phase 2: profile CRUD + global settings + descriptor upload/list +
 * server-side match (fallback for devices without a local cache).
 */

import type {
  FaceProfile,
  FaceSettings,
  StoredDescriptor,
} from '../features/face/types';

import { authFetch } from './auth';

const API = '/api/v1/face';

export interface CreateFaceProfileBody {
  display_name: string;
  is_child?: boolean;
  match_threshold?: number;
  consent_text_version: string;
}

export interface UpdateFaceProfileBody {
  display_name?: string;
  is_child?: boolean;
  match_threshold?: number;
  active?: boolean;
}

async function asJson<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = await r.text().catch(() => '');
    throw new Error(`HTTP ${r.status} ${r.statusText}: ${body.slice(0, 200)}`);
  }
  return (await r.json()) as T;
}

export async function listFaceProfiles(): Promise<FaceProfile[]> {
  return authFetch(`${API}/profiles`).then(asJson<FaceProfile[]>);
}

export async function getFaceProfile(id: string): Promise<FaceProfile> {
  return authFetch(`${API}/profiles/${encodeURIComponent(id)}`).then(asJson<FaceProfile>);
}

export async function createFaceProfile(body: CreateFaceProfileBody): Promise<FaceProfile> {
  return authFetch(`${API}/profiles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(asJson<FaceProfile>);
}

export async function updateFaceProfile(
  id: string,
  body: UpdateFaceProfileBody,
): Promise<FaceProfile> {
  return authFetch(`${API}/profiles/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(asJson<FaceProfile>);
}

export async function deleteFaceProfile(id: string): Promise<void> {
  const r = await authFetch(`${API}/profiles/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
  if (!r.ok) throw new Error(`delete failed: HTTP ${r.status}`);
}

export async function getFaceSettings(): Promise<FaceSettings> {
  return authFetch(`${API}/settings`).then(asJson<FaceSettings>);
}

export async function updateFaceSettings(s: Partial<FaceSettings>): Promise<FaceSettings> {
  return authFetch(`${API}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(s),
  }).then(asJson<FaceSettings>);
}

// ─── Descriptors ──────────────────────────────────────────────────────

export interface DescriptorPayload {
  descriptor: number[];
  source: 'enrollment' | 'continuous';
  quality?: number;
}

export async function addDescriptors(
  profileId: string,
  items: DescriptorPayload[],
): Promise<StoredDescriptor[]> {
  return authFetch(`${API}/profiles/${encodeURIComponent(profileId)}/descriptors`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  }).then(asJson<StoredDescriptor[]>);
}

export async function listDescriptors(profileId: string): Promise<StoredDescriptor[]> {
  return authFetch(
    `${API}/profiles/${encodeURIComponent(profileId)}/descriptors`,
  ).then(asJson<StoredDescriptor[]>);
}

// ─── Server-side match (fallback for fresh devices) ───────────────────

export interface MatchHit {
  profileId: string;
  displayName: string;
  isChild: boolean;
  distance: number;
  matchedDescriptorId: string;
}

export async function serverMatch(descriptor: number[]): Promise<MatchHit | null> {
  const r = await authFetch(`${API}/match`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ descriptor }),
  });
  const data = await asJson<{ match: MatchHit | null }>(r);
  return data.match;
}
