import { authFetch } from './auth';

export type CdaKind =
  | 'audio_stream'
  | 'article'
  | 'video'
  | 'podcast'
  | 'image'
  | 'document';

export interface DiscoverResult {
  kind: CdaKind | 'article_feed';
  url: string;
  title: string | null;
  source_domain: string | null;
  metadata: Record<string, unknown>;
  confidence: number;
  cached: boolean;
  duration_ms_to_resolve: number;
  content_id: string;
  fallbacks: Array<{
    url: string;
    title: string | null;
    source_domain: string | null;
    score: number;
  }>;
}

export async function discoverContent(query: string, kind: CdaKind): Promise<DiscoverResult> {
  const r = await authFetch('/api/v1/cda/discover', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, content_type: kind, modifiers: {} }),
  });
  if (!r.ok) {
    const detail = await r
      .json()
      .then((j) => j.detail)
      .catch(() => `HTTP ${r.status}`);
    throw new Error(detail);
  }
  return r.json();
}

export interface KbItem {
  id: string;
  content_type: string;
  url: string;
  title: string | null;
  source_domain: string | null;
  metadata: Record<string, unknown>;
  confidence_score: number;
  success_count: number;
  failure_count: number;
  last_verified_at: string | null;
  discovered_via: string | null;
  discovered_at: string;
  is_active: boolean;
}

export async function listKb(opts: { content_type?: string; limit?: number } = {}): Promise<KbItem[]> {
  const params = new URLSearchParams();
  if (opts.content_type) params.set('content_type', opts.content_type);
  if (opts.limit) params.set('limit', String(opts.limit));
  const qs = params.toString();
  const r = await authFetch(`/api/v1/cda/items${qs ? '?' + qs : ''}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function feedbackStarted(content_id: string): Promise<void> {
  await authFetch('/api/v1/cda/feedback/started', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content_id }),
  });
}

export async function feedbackStopped(args: {
  content_id: string;
  played_seconds: number;
  reason: 'user_stop' | 'ended' | 'error' | 'switched';
}): Promise<void> {
  await authFetch('/api/v1/cda/feedback/stopped', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  });
}

export async function feedbackRegenerated(content_id: string): Promise<void> {
  await authFetch('/api/v1/cda/feedback/regenerated', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content_id }),
  });
}
