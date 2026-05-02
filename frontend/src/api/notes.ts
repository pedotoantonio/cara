import { authFetch } from './auth';

const API = '/api/v1';

export interface Note {
  id: string;
  title: string;
  body: string;
  created_at: string;
  updated_at: string;
}

export async function listNotes(): Promise<Note[]> {
  const r = await authFetch(`${API}/notes`);
  if (!r.ok) throw new Error(`list failed: ${r.status}`);
  return r.json();
}

export async function createNote(title: string, body = ''): Promise<Note> {
  const r = await authFetch(`${API}/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, body }),
  });
  if (!r.ok) throw new Error(`create failed: ${r.status}`);
  return r.json();
}

export async function updateNote(
  id: string,
  changes: { title?: string; body?: string },
): Promise<Note> {
  const r = await authFetch(`${API}/notes/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  });
  if (!r.ok) throw new Error(`update failed: ${r.status}`);
  return r.json();
}

export async function deleteNote(id: string): Promise<void> {
  const r = await authFetch(`${API}/notes/${id}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`delete failed: ${r.status}`);
}
