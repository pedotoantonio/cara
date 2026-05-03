/**
 * Admin diagnostics page (/admin/diagnostics).
 *
 * Three sections:
 *  1. Component health grid — green/yellow/red dot per subsystem.
 *  2. Recent events ring buffer — what just happened in the backend.
 *  3. Self-test buttons — round-trip probes for each capability.
 */

import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';

import type { User } from '../api/auth';
import {
  clearDiagEvents,
  fetchDiagEvents,
  fetchDiagnostics,
  testDiscover,
  testLlm,
  testSpeak,
  testWhoIsHome,
  type DiagCheck,
  type DiagEvent,
  type DiagOverview,
} from '../api/diagnostics';

const STATUS_DOT: Record<DiagCheck['status'], string> = {
  ok: 'bg-emerald-400',
  warn: 'bg-amber-400',
  error: 'bg-rose-500',
};

export function DiagnosticsPage() {
  const { user } = useOutletContext<{ user: User }>();
  const navigate = useNavigate();
  useEffect(() => {
    if (!user.is_admin) navigate('/chat', { replace: true });
  }, [user, navigate]);

  const [overview, setOverview] = useState<DiagOverview | null>(null);
  const [events, setEvents] = useState<DiagEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [running, setRunning] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [ov, ev] = await Promise.all([
        fetchDiagnostics(),
        fetchDiagEvents({ limit: 50, kind: filter || undefined }),
      ]);
      setOverview(ov);
      setEvents(ev.events);
    } catch (e) {
      console.error('[diagnostics]', e);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(refresh, 10_000);
    return () => clearInterval(t);
  }, [autoRefresh, refresh]);

  async function runTest(label: string, fn: () => Promise<unknown>) {
    setRunning(label);
    setTestResult(null);
    try {
      const r = await fn();
      setTestResult(`${label}: ${JSON.stringify(r, null, 2)}`);
    } catch (e) {
      setTestResult(`${label}: ERRORE — ${(e as Error).message}`);
    } finally {
      setRunning(null);
      // refresh events after a test so the new entries appear immediately
      void refresh();
    }
  }

  if (loading && !overview) {
    return <main className="flex-1 p-6 bg-slate-900 text-slate-500 text-sm">Carico…</main>;
  }

  return (
    <main className="flex-1 overflow-y-auto bg-slate-900 text-slate-100">
      <div className="max-w-5xl mx-auto p-4 md:p-6 space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-medium">Diagnosi sistema</h1>
            <p className="text-xs text-slate-500 mt-0.5">
              Aggiornato:{' '}
              {overview?.ts ? new Date(overview.ts).toLocaleTimeString('it-IT') : '—'}
            </p>
          </div>
          <div className="flex gap-2 items-center text-xs">
            <label className="flex items-center gap-1 cursor-pointer">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="accent-emerald-500"
              />
              Auto-refresh 10 s
            </label>
            <button
              type="button"
              onClick={refresh}
              className="rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-1.5"
            >
              ↻ Aggiorna
            </button>
          </div>
        </header>

        {/* Component health */}
        <section className="rounded-2xl bg-slate-800/60 border border-slate-700 p-4 space-y-2">
          <h2 className="text-sm font-medium">Stato componenti</h2>
          {overview && (
            <p className="text-xs text-slate-500">
              {overview.summary.ok} ok · {overview.summary.warn} warning ·{' '}
              {overview.summary.error} errori
            </p>
          )}
          <ul className="grid sm:grid-cols-2 gap-2">
            {overview?.checks.map((c) => (
              <li
                key={c.name}
                className="flex items-start gap-2 rounded-lg bg-slate-900/40 border border-slate-700/40 px-3 py-2 text-xs"
              >
                <span
                  className={`w-2.5 h-2.5 rounded-full mt-1 shrink-0 ${STATUS_DOT[c.status]}`}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex justify-between items-baseline gap-2">
                    <span className="text-slate-100 font-medium">{c.name}</span>
                    {c.latency_ms !== null && (
                      <span className="text-slate-500">{c.latency_ms} ms</span>
                    )}
                  </div>
                  <p className="text-slate-400 mt-0.5">{c.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>

        {/* Self-tests */}
        <section className="rounded-2xl bg-slate-800/60 border border-slate-700 p-4 space-y-3">
          <h2 className="text-sm font-medium">Self-test</h2>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!!running}
              onClick={() => runTest('Test voce TTS', () => testSpeak())}
              className="rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-3 py-2 text-xs font-medium"
            >
              {running === 'Test voce TTS' ? '…' : '🔊 Test voce'}
            </button>
            <button
              type="button"
              disabled={!!running}
              onClick={() => runTest('Test LLM', () => testLlm())}
              className="rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-3 py-2 text-xs font-medium"
            >
              {running === 'Test LLM' ? '…' : '🤖 Test LLM'}
            </button>
            <button
              type="button"
              disabled={!!running}
              onClick={() => runTest('Test ricerca CDA', () => testDiscover('meteo Roma'))}
              className="rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-3 py-2 text-xs font-medium"
            >
              {running === 'Test ricerca CDA' ? '…' : '🌐 Test ricerca'}
            </button>
            <button
              type="button"
              disabled={!!running}
              onClick={() => runTest('Test riconoscimento', () => testWhoIsHome())}
              className="rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-3 py-2 text-xs font-medium"
            >
              {running === 'Test riconoscimento' ? '…' : '👤 Test telecamere'}
            </button>
          </div>
          {testResult && (
            <pre className="text-[11px] text-slate-300 bg-slate-900/60 border border-slate-700/40 rounded-lg p-2 overflow-x-auto whitespace-pre-wrap">
              {testResult}
            </pre>
          )}
        </section>

        {/* Recent events */}
        <section className="rounded-2xl bg-slate-800/60 border border-slate-700 p-4 space-y-2">
          <header className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-medium">Eventi recenti</h2>
            <div className="flex items-center gap-2">
              <input
                type="text"
                placeholder="Filtra per kind (es: chat,asr)"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="text-xs rounded-lg bg-slate-900 border border-slate-700 px-2 py-1"
              />
              <button
                type="button"
                onClick={async () => {
                  await clearDiagEvents();
                  void refresh();
                }}
                className="text-xs rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-2 py-1"
              >
                Pulisci
              </button>
            </div>
          </header>
          {events.length === 0 ? (
            <p className="text-xs text-slate-500">Niente da mostrare per ora.</p>
          ) : (
            <ul className="text-xs space-y-1 max-h-96 overflow-y-auto">
              {events.map((e, i) => (
                <li
                  key={`${e.ts}-${i}`}
                  className="flex gap-2 items-start text-slate-400 border-b border-slate-700/30 pb-1"
                >
                  <span className="text-slate-500 shrink-0 font-mono text-[10px]">
                    {new Date(e.ts).toLocaleTimeString('it-IT', {
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit',
                    })}
                  </span>
                  <span className="text-emerald-400 shrink-0">{e.kind}</span>
                  {e.duration_ms !== null && (
                    <span className="text-slate-500 shrink-0">{e.duration_ms} ms</span>
                  )}
                  <span className="text-slate-300 truncate">
                    {Object.keys(e.data).length > 0 ? JSON.stringify(e.data) : ''}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  );
}
