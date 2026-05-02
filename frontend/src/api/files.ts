import { authFetch, getToken } from './auth';

const API = '/api/v1';

export interface FileMeta {
  id: string;
  filename: string;
  mime_type: string;
  kind: string;
  size_bytes: number;
  sha256: string;
  summary: string | null;
  created_at: string;
}

export async function uploadFile(file: File): Promise<FileMeta> {
  const fd = new FormData();
  fd.append('file', file);
  // authFetch's GET helper does not handle FormData well — go raw with the
  // bearer token directly, matching the streamChat pattern.
  const r = await fetch(`${API}/files`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${getToken() ?? ''}` },
    body: fd,
  });
  if (!r.ok) {
    const detail = await r.json().then((j) => j.detail).catch(() => `HTTP ${r.status}`);
    throw new Error(detail);
  }
  return r.json();
}

export async function listFiles(): Promise<FileMeta[]> {
  const r = await authFetch(`${API}/files`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function deleteFile(id: string): Promise<void> {
  const r = await authFetch(`${API}/files/${id}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}
