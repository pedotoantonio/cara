// Service board for the Wall — list every CARA-related container with
// a color-coded health pill and start/stop/restart buttons. LAN-only,
// no auth (the backend gates by CIDR).
//
// Polling cadence: 5s. Action buttons disable themselves while a
// command is in flight to that service so quick double-taps don't fan
// out into multiple Docker calls.

import { useEffect, useMemo, useState } from 'react';

import {
  fetchHealth, fetchServices, fetchWatchdog, runHealthNow,
  serviceAction, setWatchdog,
} from '../../api/wall';
import type {
  HealthSnapshot, HealthStatus, WallService, WallServicesSnapshot,
  WallServiceColor, WallWatchdogStatus,
} from '../../api/wall';

const COLOR_PILL: Record<WallServiceColor, string> = {
  green: 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30',
  yellow: 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30',
  red: 'bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30',
  gray: 'bg-zinc-500/15 text-zinc-300 ring-1 ring-zinc-500/30',
};
const COLOR_DOT: Record<WallServiceColor, string> = {
  green: 'bg-emerald-400',
  yellow: 'bg-amber-400',
  red: 'bg-rose-400',
  gray: 'bg-zinc-400',
};

const HEALTH_PILL: Record<HealthStatus, string> = {
  ok: 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30',
  warn: 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30',
  fail: 'bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30',
  unknown: 'bg-zinc-500/15 text-zinc-400 ring-1 ring-zinc-500/30',
};
const HEALTH_DOT: Record<HealthStatus, string> = {
  ok: 'bg-emerald-400',
  warn: 'bg-amber-400',
  fail: 'bg-rose-400',
  unknown: 'bg-zinc-400',
};

function relativeTime(iso: string | null): string {
  if (!iso) return '—';
  try {
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return '—';
    const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (sec < 60) return `${sec}s fa`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m fa`;
    const h = Math.floor(min / 60);
    if (h < 24) return `${h}h fa`;
    const d = Math.floor(h / 24);
    return `${d}g fa`;
  } catch {
    return '—';
  }
}

function ProbeRow({ probe }: { probe: import('../../api/wall').HealthProbe }) {
  const subtitle = probe.status === 'ok'
    ? `${probe.duration_ms ?? '—'} ms · ${relativeTime(probe.last_check_at)}`
    : probe.status === 'unknown'
      ? 'mai eseguita'
      : probe.error || 'errore';
  return (
    <li className="flex items-start justify-between gap-3 rounded-lg bg-bg/30 ring-1 ring-white/5 px-3 py-2">
      <div className="min-w-0">
        <div className="text-sm truncate">{probe.label}</div>
        <div
          className="text-[11px] text-fg-muted truncate"
          title={`${probe.error || ''}${probe.last_ok_at ? ` · OK l'ultima volta ${probe.last_ok_at}` : ''}`}
        >
          {subtitle}
        </div>
      </div>
      <span
        className={`shrink-0 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] ${HEALTH_PILL[probe.status]}`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${HEALTH_DOT[probe.status]}`} />
        {probe.status === 'ok' ? 'OK'
          : probe.status === 'warn' ? 'avviso'
          : probe.status === 'fail' ? `KO×${probe.fail_streak}`
          : '—'}
      </span>
    </li>
  );
}

function uptime(startedAt: string | null, running: boolean): string {
  if (!running || !startedAt) return '—';
  try {
    const t = Date.parse(startedAt);
    if (Number.isNaN(t)) return '—';
    const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (sec < 60) return `${sec}s`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m`;
    const h = Math.floor(min / 60);
    if (h < 24) return `${h}h ${min % 60}m`;
    const d = Math.floor(h / 24);
    return `${d}g ${h % 24}h`;
  } catch {
    return '—';
  }
}

export function WallServicesPage() {
  const [data, setData] = useState<WallServicesSnapshot | null>(null);
  const [watchdog, setWatchdogState] = useState<WallWatchdogStatus | null>(null);
  const [health, setHealth] = useState<HealthSnapshot | null>(null);
  const [healthBusy, setHealthBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [flash, setFlash] = useState<{ name: string; msg: string; ok: boolean } | null>(null);

  async function refresh() {
    try {
      const [snap, wd, h] = await Promise.all([
        fetchServices(), fetchWatchdog(), fetchHealth(),
      ]);
      setData(snap);
      setWatchdogState(wd);
      setHealth(h);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function runHealth() {
    setHealthBusy(true);
    try {
      const h = await runHealthNow();
      setHealth(h);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setHealthBusy(false);
    }
  }

  useEffect(() => {
    void refresh();
    const id = window.setInterval(refresh, 5_000);
    return () => window.clearInterval(id);
  }, []);

  async function toggleWatchdog() {
    if (!watchdog) return;
    try {
      const r = await setWatchdog(!watchdog.enabled);
      setWatchdogState({ ...watchdog, enabled: r.enabled });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function act(svc: WallService, action: 'start' | 'stop' | 'restart') {
    setBusy((b) => ({ ...b, [svc.name]: true }));
    try {
      const r = await serviceAction(svc.name, action);
      setFlash({ name: svc.name, msg: `${action} ok (${r.status})`, ok: true });
      await refresh();
    } catch (e) {
      setFlash({ name: svc.name, msg: `${action}: ${(e as Error).message}`, ok: false });
    } finally {
      setBusy((b) => ({ ...b, [svc.name]: false }));
      window.setTimeout(() => setFlash((f) => (f && f.name === svc.name ? null : f)), 4000);
    }
  }

  const grouped = useMemo(() => {
    const map = new Map<string, WallService[]>();
    if (data) {
      for (const item of data.items) {
        const k = item.category;
        const a = map.get(k) ?? [];
        a.push(item);
        map.set(k, a);
      }
    }
    return Array.from(map.entries());
  }, [data]);

  return (
    <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4 space-y-6">
      <header className="flex items-baseline justify-between">
        <h2 className="text-2xl font-semibold tracking-tight">Servizi CARA</h2>
        {data && (
          <div className="flex gap-3 text-sm text-fg-muted">
            <span className="inline-flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${COLOR_DOT.green}`} />
              {data.summary.green} ok
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${COLOR_DOT.yellow}`} />
              {data.summary.yellow} attesa
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${COLOR_DOT.red}`} />
              {data.summary.red} giù
            </span>
            {data.summary.gray > 0 && (
              <span className="inline-flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${COLOR_DOT.gray}`} />
                {data.summary.gray} mancanti
              </span>
            )}
          </div>
        )}
      </header>

      {error && (
        <div className="rounded-md bg-rose-500/10 ring-1 ring-rose-500/30 px-3 py-2 text-rose-300 text-sm">
          {error}
        </div>
      )}

      {watchdog && (
        <section className="rounded-xl bg-bg-elevated/60 ring-1 ring-white/5 p-4 flex items-center justify-between gap-4">
          <div>
            <div className="font-medium">Auto-recovery (modalità cluster single-host)</div>
            <div className="text-xs text-fg-muted mt-0.5 max-w-xl">
              Quando attivo, ogni 30s un agente controlla i container: se uno resta non-verde
              per ≥{watchdog.min_bad_ticks} tick consecutivi prova un riavvio automatico e manda
              alert su Telegram (escalation a {watchdog.escalate_bad_ticks} tick). Su single-host
              non è possibile un vero failover su un secondo nodo: questo è il sostituto
              pragmatico — recupero veloce + notifica.
            </div>
          </div>
          <button
            onClick={toggleWatchdog}
            className={`shrink-0 px-4 py-2 rounded-lg text-sm font-medium transition ${
              watchdog.enabled
                ? 'bg-emerald-600/30 text-emerald-200 ring-1 ring-emerald-500/40'
                : 'bg-zinc-700/40 text-zinc-300 ring-1 ring-zinc-500/30'
            }`}
          >
            {watchdog.enabled ? 'Attivo' : 'Disattivato'}
          </button>
        </section>
      )}

      {health && (
        <section className="rounded-xl bg-bg-elevated/60 ring-1 ring-white/5 p-4 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="font-medium">Salute funzionale</div>
              <div className="text-xs text-fg-muted mt-0.5">
                Sonde end-to-end ogni 5 min (DB query, Redis ping, Chroma, MinIO,
                Frigate, Frigate Faces, Telegram bot, /wall/summary, Open-Meteo).
                Verde se la dipendenza risponde davvero.
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="hidden sm:inline-flex items-center gap-3 text-xs text-fg-muted">
                <span className="inline-flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  {health.summary.ok}
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                  {health.summary.warn}
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                  {health.summary.fail}
                </span>
                {health.summary.unknown > 0 && (
                  <span className="inline-flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-zinc-400" />
                    {health.summary.unknown}
                  </span>
                )}
              </span>
              <button
                onClick={runHealth}
                disabled={healthBusy}
                className="px-3 py-1.5 rounded-md bg-accent/20 hover:bg-accent/30 disabled:opacity-30 text-fg text-sm transition"
              >
                {healthBusy ? 'Verifica…' : 'Verifica ora'}
              </button>
            </div>
          </div>
          <ul className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
            {health.items.map((p) => (
              <ProbeRow key={p.name} probe={p} />
            ))}
          </ul>
        </section>
      )}

      {grouped.map(([category, items]) => (
        <section key={category} className="space-y-2">
          <h3 className="text-sm uppercase tracking-wider text-fg-muted">{category}</h3>
          <ul className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {items.map((svc) => (
              <li
                key={svc.name}
                className="rounded-xl bg-bg-elevated/60 ring-1 ring-white/5 p-4 flex flex-col gap-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{svc.label}</div>
                    <div className="text-xs text-fg-muted font-mono truncate">
                      {svc.name}
                      {svc.role === 'stateful' && (
                        <span className="ml-2 inline-block px-1.5 py-0.5 rounded bg-zinc-700/60 text-[10px] uppercase tracking-wide">
                          stato
                        </span>
                      )}
                    </div>
                  </div>
                  <span
                    className={`shrink-0 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs ${COLOR_PILL[svc.color]}`}
                    title={svc.status}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${COLOR_DOT[svc.color]}`} />
                    {svc.status}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-fg-muted">
                  <span>uptime</span>
                  <span className="text-fg text-right tabular-nums">
                    {uptime(svc.started_at, svc.running)}
                  </span>
                  <span>restart</span>
                  <span className="text-fg text-right tabular-nums">{svc.restart_count}</span>
                  {!svc.running && svc.exit_code !== null && (
                    <>
                      <span>exit</span>
                      <span className="text-fg text-right tabular-nums">{svc.exit_code}</span>
                    </>
                  )}
                </div>

                <div className="flex gap-2 pt-1">
                  <button
                    onClick={() => act(svc, 'start')}
                    disabled={busy[svc.name] || (svc.running && svc.color === 'green')}
                    className="flex-1 px-3 py-1.5 rounded-md bg-emerald-600/20 hover:bg-emerald-600/30 disabled:opacity-30 disabled:cursor-not-allowed text-emerald-200 text-sm transition"
                  >
                    Avvia
                  </button>
                  <button
                    onClick={() => act(svc, 'restart')}
                    disabled={busy[svc.name]}
                    className="flex-1 px-3 py-1.5 rounded-md bg-amber-600/20 hover:bg-amber-600/30 disabled:opacity-30 disabled:cursor-not-allowed text-amber-200 text-sm transition"
                  >
                    Riavvia
                  </button>
                  <button
                    onClick={() => act(svc, 'stop')}
                    disabled={busy[svc.name] || !svc.running}
                    className="flex-1 px-3 py-1.5 rounded-md bg-rose-600/20 hover:bg-rose-600/30 disabled:opacity-30 disabled:cursor-not-allowed text-rose-200 text-sm transition"
                  >
                    Ferma
                  </button>
                </div>

                {flash && flash.name === svc.name && (
                  <div
                    className={`text-xs rounded px-2 py-1 ${
                      flash.ok
                        ? 'bg-emerald-500/10 text-emerald-300'
                        : 'bg-rose-500/10 text-rose-300'
                    }`}
                  >
                    {flash.msg}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}

      {!data && !error && (
        <div className="text-sm text-fg-muted">Caricamento servizi…</div>
      )}
    </div>
  );
}
