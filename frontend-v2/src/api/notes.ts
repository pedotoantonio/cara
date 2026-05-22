import { apiDelete, apiGet, apiPatch, apiPost } from './client';

export interface Note {
  id: string;
  user_id: number;
  title: string | null;
  content: string;
  created_at: string;
  updated_at: string;
}

export async function listNotes(): Promise<Note[]> {
  return apiGet<Note[]>('/notes');
}

export async function createNote(body: { title?: string | null; content: string }): Promise<Note> {
  return apiPost<Note>('/notes', body);
}

export async function updateNote(
  id: string,
  patch: { title?: string | null; content?: string },
): Promise<Note> {
  return apiPatch<Note>(`/notes/${id}`, patch);
}

export async function deleteNote(id: string): Promise<void> {
  return apiDelete(`/notes/${id}`);
}
