/**
 * Admin client for /api/v1/admin/persons — face DB management.
 * Mirrors the backend endpoints exactly. All calls require admin JWT.
 */

import { authFetch } from './auth';

const API = '/api/v1/admin/persons';

export interface Person {
  id: number;
  name: string;
  notify: boolean;
  sighting_count: number;
  last_seen: string | null;
  latest_image: string | null;
}

export interface UnknownSighting {
  id: number;
  camera: string | null;
  timestamp: string | null;
  image_url: string | null;
}

export async function listPersons(): Promise<Person[]> {
  const r = await authFetch(API);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createPerson(name: string, notify = true): Promise<Person> {
  const r = await authFetch(API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, notify }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function updatePerson(
  id: number,
  patch: { name?: string; notify?: boolean },
): Promise<Person> {
  const r = await authFetch(`${API}/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function deletePerson(id: number): Promise<void> {
  const r = await authFetch(`${API}/${id}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

export async function uploadPhoto(id: number, file: File): Promise<unknown> {
  const fd = new FormData();
  fd.append('file', file, file.name);
  const r = await authFetch(`${API}/${id}/photos`, { method: 'POST', body: fd });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listUnknowns(limit = 50): Promise<UnknownSighting[]> {
  const r = await authFetch(`${API}/unknowns?limit=${limit}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function assignSighting(sightingId: number, personId: number): Promise<void> {
  const r = await authFetch(`${API}/unknowns/${sightingId}/assign`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ person_id: personId }),
  });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

export async function createPersonFromSighting(
  sightingId: number,
  name: string,
  notify = true,
): Promise<Person> {
  const r = await authFetch(`${API}/unknowns/${sightingId}/create_person`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, notify }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
