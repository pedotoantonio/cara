import { apiGet, apiPost } from './client';

export type CdaKind = 'radio' | 'article' | 'video' | 'podcast' | 'image' | 'document';

export interface CdaItem {
  id: number;
  kind: CdaKind;
  title: string;
  url: string;
  source?: string | null;
  description?: string | null;
  thumbnail_url?: string | null;
  confidence: number;
  active: boolean;
  created_at: string;
  last_verified_at?: string | null;
}

export async function listCdaItems(kind?: CdaKind, activeOnly = true): Promise<CdaItem[]> {
  const params = new URLSearchParams();
  if (kind) params.set('kind', kind);
  params.set('active_only', String(activeOnly));
  try {
    return await apiGet<CdaItem[]>(`/cda/items?${params.toString()}`);
  } catch {
    return [];
  }
}

export async function feedbackCda(itemId: number, action: 'like' | 'dislike'): Promise<void> {
  await apiPost(`/cda/items/${itemId}/feedback`, { action }).catch(() => undefined);
}
