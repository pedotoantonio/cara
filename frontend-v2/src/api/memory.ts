import { apiDelete, apiGet, apiPost } from './client';

export interface Fact {
  id: number;
  user_id: number;
  text: string;
  fact_type: string;
  source: string;
  confidence: number;
  active: boolean;
  created_at: string;
}

export async function listMyFacts(): Promise<Fact[]> {
  try {
    return await apiGet<Fact[]>('/memory/facts');
  } catch {
    return [];
  }
}

export async function deactivateFact(id: number): Promise<void> {
  return apiDelete(`/memory/facts/${id}`);
}

export async function exportMyMemory(): Promise<unknown> {
  return apiPost<unknown>('/memory/export', {});
}

export async function purgeMyMemory(): Promise<void> {
  await apiPost('/memory/purge', {}).catch(() => undefined);
}
