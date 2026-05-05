// /pair — page shown to a brand-new device that has no JWT yet.
// Generates a 6-digit pairing code, polls for finalisation, stores the
// device JWT in localStorage when the admin completes the flow.
import { useEffect, useRef, useState } from 'react';

import { getPairStatus, startPair, type PairStatus } from '../api/devices';

const POLL_INTERVAL_MS = 2000;
const DEVICE_TOKEN_KEY = 'cara.device_token.v1';
const DEVICE_ID_KEY = 'cara.device_id.v1';
const DEVICE_NAME_KEY = 'cara.device_name.v1';
const DEVICE_SURFACE_KEY = 'cara.device_surface.v1';


function detectSurface(): 'mobile' | 'desktop' | 'wall' {
  if (typeof window === 'undefined') return 'mobile';
  // Loose heuristic: large viewport + coarse pointer + no touch hints
  // → desktop. Tablet/phone get mobile. Wall is opt-in per finalize.
  const hasTouch = 'ontouchstart' in window;
  const wide = window.innerWidth >= 1280;
  if (wide && !hasTouch) return 'desktop';
  return 'mobile';
}


export function PairPage() {
  const [code, setCode] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<Date | null>(null);
  const [status, setStatus] = useState<PairStatus['status']>('waiting');
  const [paired, setPaired] = useState<PairStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Start pair on mount.
  useEffect(() => {
    (async () => {
      try {
        const ticket = await startPair({
          suggestedSurface: detectSurface(),
        });
        setCode(ticket.code);
        setExpiresAt(new Date(ticket.expires_at));
      } catch (e) {
        setErr((e as Error).message);
      }
    })();
  }, []);

  // Poll status.
  useEffect(() => {
    if (!code) return;
    pollRef.current = setInterval(async () => {
      try {
        const s = await getPairStatus(code);
        setStatus(s.status);
        if (s.status === 'paired' && s.device_token) {
          // Persist + stop polling.
          try {
            localStorage.setItem(DEVICE_TOKEN_KEY, s.device_token);
            if (s.device_id) localStorage.setItem(DEVICE_ID_KEY, s.device_id);
            if (s.friendly_name)
              localStorage.setItem(DEVICE_NAME_KEY, s.friendly_name);
            if (s.surface_class)
              localStorage.setItem(DEVICE_SURFACE_KEY, s.surface_class);
          } catch {
            // localStorage blocked — non-fatal, the user just won't auto-resume
          }
          setPaired(s);
          if (pollRef.current) clearInterval(pollRef.current);
        } else if (s.status === 'expired') {
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch (e) {
        setErr((e as Error).message);
      }
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [code]);

  // Restart on expired.
  function reset() {
    setCode(null);
    setExpiresAt(null);
    setStatus('waiting');
    setErr(null);
    setPaired(null);
    (async () => {
      try {
        const ticket = await startPair({
          suggestedSurface: detectSurface(),
        });
        setCode(ticket.code);
        setExpiresAt(new Date(ticket.expires_at));
      } catch (e) {
        setErr((e as Error).message);
      }
    })();
  }

  // Once paired, send the user to the home page after a brief delay.
  useEffect(() => {
    if (paired) {
      const t = setTimeout(() => {
        window.location.href = '/';
      }, 1500);
      return () => clearTimeout(t);
    }
  }, [paired]);

  return (
    <main className="min-h-dvh flex items-center justify-center bg-slate-900 text-slate-100 p-6">
      <div className="w-full max-w-md space-y-6">
        <header className="text-center">
          <h1 className="text-3xl font-light tracking-tight">cara</h1>
          <p className="text-sm text-slate-400 mt-1">
            Aggiungi questo dispositivo alla famiglia
          </p>
        </header>

        {err && (
          <p className="text-xs text-rose-400 bg-rose-950/40 border border-rose-900 rounded-lg p-3 text-center">
            {err}
          </p>
        )}

        {paired ? (
          <div className="text-center space-y-3 rounded-2xl bg-emerald-900/20 border border-emerald-800 p-6">
            <p className="text-2xl">✓</p>
            <p className="text-sm font-medium">
              Aggiunto come <strong>{paired.friendly_name}</strong>
            </p>
            <p className="text-xs text-slate-400">Ti porto in casa…</p>
          </div>
        ) : status === 'expired' ? (
          <div className="text-center space-y-3 rounded-2xl bg-amber-900/20 border border-amber-800 p-6">
            <p className="text-sm">Il codice è scaduto.</p>
            <button
              type="button"
              onClick={reset}
              className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-sm font-medium"
            >
              Genera un nuovo codice
            </button>
          </div>
        ) : code ? (
          <div className="text-center space-y-4 rounded-2xl bg-slate-800/60 border border-slate-700 p-6">
            <p className="text-xs text-slate-400">Inserisci questo codice nel</p>
            <p className="text-xs text-slate-400">
              pannello admin di un altro dispositivo già paired:
            </p>
            <p
              className="text-5xl font-mono tracking-[0.4em] py-3 text-emerald-300 select-all"
              aria-label={`Codice ${code.split('').join(' ')}`}
            >
              {code}
            </p>
            <p className="text-[11px] text-slate-500">
              Apri <code>/admin/devices</code> sull'altro dispositivo →{' '}
              <strong>+ Aggiungi</strong> → digita il codice.
            </p>
            {expiresAt && (
              <p className="text-[10px] text-slate-600">
                Scade alle {expiresAt.toLocaleTimeString('it-IT')}
              </p>
            )}
            <p className="text-xs text-slate-400 pt-2">
              <span className="inline-block animate-pulse">●</span> Aspetto la
              conferma…
            </p>
          </div>
        ) : (
          <p className="text-center text-sm text-slate-400">Genero il codice…</p>
        )}
      </div>
    </main>
  );
}
