import { apiDelete, apiGet, apiPatch, apiPost } from './client';

export interface Task {
  id: string;
  user_id: number;
  title: string;
  done: boolean;
  due_date: string | null;
  created_at: string;
  completed_at: string | null;
  wall_visible?: boolean;
}

export async function listTasks(): Promise<Task[]> {
  return apiGet<Task[]>('/tasks');
}

export async function createTask(body: { title: string; due_date?: string | null }): Promise<Task> {
  return apiPost<Task>('/tasks', body);
}

export async function updateTask(
  id: string,
  patch: { title?: string; done?: boolean; due_date?: string | null },
): Promise<Task> {
  return apiPatch<Task>(`/tasks/${id}`, patch);
}

export async function deleteTask(id: string): Promise<void> {
  return apiDelete(`/tasks/${id}`);
}
