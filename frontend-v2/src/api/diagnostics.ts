import { apiGet } from './client';

export interface DiagnosticItem {
  name: string;
  status: 'ok' | 'warn' | 'fail' | 'unknown';
  detail?: string;
  duration_ms?: number;
}

export interface DiagnosticsSnapshot {
  items: DiagnosticItem[];
  generated_at: string;
}

export async function fetchDiagnostics(): Promise<DiagnosticsSnapshot> {
  try {
    return await apiGet<DiagnosticsSnapshot>('/diagnostics');
  } catch {
    return { items: [], generated_at: new Date().toISOString() };
  }
}
