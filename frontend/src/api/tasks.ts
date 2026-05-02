import { authFetch } from './auth';

const API = '/api/v1';

export interface Task {
  id: string;
  title: string;
  done: boolean;
  created_at: string;
  completed_at: string | null;
  due_date: string | null;
}

export async function listTasks(includeDone = true): Promise<Task[]> {
  const r = await authFetch(`${API}/tasks?include_done=${includeDone}`);
  if (!r.ok) throw new Error(`list failed: ${r.status}`);
  return r.json();
}

export async function createTask(title: string, dueDate?: string | null): Promise<Task> {
  const body: Record<string, unknown> = { title };
  if (dueDate) body.due_date = dueDate;
  const r = await authFetch(`${API}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`create failed: ${r.status}`);
  return r.json();
}

export async function updateTask(
  id: string,
  changes: { title?: string; done?: boolean; due_date?: string | null },
): Promise<Task> {
  const r = await authFetch(`${API}/tasks/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  });
  if (!r.ok) throw new Error(`update failed: ${r.status}`);
  return r.json();
}

export async function deleteTask(id: string): Promise<void> {
  const r = await authFetch(`${API}/tasks/${id}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`delete failed: ${r.status}`);
}
