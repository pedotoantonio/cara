import { authFetch } from './auth';

export interface DiagCheck {
  name: string;
  status: 'ok' | 'warn' | 'error';
  latency_ms: number | null;
  detail: string;
}

export interface DiagOverview {
  checks: DiagCheck[];
  summary: { ok: number; warn: number; error: number };
  ts: string;
}

export interface DiagEvent {
  ts: string;
  kind: string;
  user_id: number | null;
  duration_ms: number | null;
  data: Record<string, unknown>;
}

export interface DiagEventsResponse {
  events: DiagEvent[];
  stats: Record<string, number>;
}

export async function fetchDiagnostics(): Promise<DiagOverview> {
  const r = await authFetch('/api/v1/admin/diagnostics');
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function fetchDiagEvents(opts: { limit?: number; kind?: string } = {}): Promise<DiagEventsResponse> {
  const params = new URLSearchParams();
  if (opts.limit) params.set('limit', String(opts.limit));
  if (opts.kind) params.set('kind', opts.kind);
  const qs = params.toString();
  const r = await authFetch(`/api/v1/admin/diagnostics/events${qs ? '?' + qs : ''}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function clearDiagEvents(): Promise<void> {
  await authFetch('/api/v1/admin/diagnostics/events', { method: 'DELETE' });
}

export async function tailDiagLog(lines: number = 200): Promise<string> {
  const r = await authFetch(`/api/v1/admin/diagnostics/log?lines=${lines}`);
  return r.text();
}

export async function testSpeak(text: string = 'CARA test, mi senti?'): Promise<{
  text: string; wav_bytes: number; sample_rate: number; elapsed_ms: number;
}> {
  const r = await authFetch('/api/v1/admin/diagnostics/test/speak', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function testLlm(prompt: string = 'Rispondi soltanto OK'): Promise<{
  text: string; tokens: number; ttft_s: number; total_s: number;
  tok_per_s: number; mode: string;
}> {
  const r = await authFetch('/api/v1/admin/diagnostics/test/llm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, max_new_tokens: 16 }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function testDiscover(query: string = 'meteo Roma'): Promise<{
  ok: boolean; url?: string; title?: string; source_domain?: string;
  cached?: boolean; elapsed_ms: number; error?: string;
}> {
  const r = await authFetch('/api/v1/admin/diagnostics/test/discover', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, kind: 'article' }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function testWhoIsHome(): Promise<{
  ok: boolean; people?: Array<{ name: string; last_seen: string }>;
  elapsed_ms: number; error?: string;
}> {
  const r = await authFetch('/api/v1/admin/diagnostics/test/who_is_home', {
    method: 'POST',
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
