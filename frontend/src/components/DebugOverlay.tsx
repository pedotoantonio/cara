/**
 * Debug overlay — toggleable panel that mirrors all `[cara-*]` console.log
 * lines in real time. Activated with Ctrl+Shift+D (or Cmd+Shift+D on Mac).
 *
 * Zero cost when off: console.log is only patched once the panel is opened
 * for the first time. Buffer caps at 200 events to keep memory bounded.
 */

import { useEffect, useRef, useState } from 'react';

const CARA_PREFIX = /^\[cara-[a-z]+\]/i;

interface DebugEvent {
  ts: number;
  prefix: string;
  body: string;
}

const _buffer: DebugEvent[] = [];
let _patched = false;

function ensurePatched() {
  if (_patched) return;
  _patched = true;
  const orig = console.log.bind(console);
  console.log = (...args: unknown[]) => {
    orig(...args);
    if (args.length === 0) return;
    const first = String(args[0] ?? '');
    if (!CARA_PREFIX.test(first)) return;
    try {
      const body = args
        .slice(1)
        .map((a) => (typeof a === 'string' ? a : JSON.stringify(a)))
        .join(' ');
      _buffer.push({ ts: Date.now(), prefix: first, body });
      if (_buffer.length > 200) _buffer.splice(0, _buffer.length - 200);
      _emit();
    } catch {
      // ignore — we never want logging itself to throw
    }
  };
}

const _listeners = new Set<() => void>();
function _emit() {
  for (const fn of _listeners) fn();
}

export function DebugOverlay() {
  const [open, setOpen] = useState(false);
  const [, force] = useState(0);
  const filter = useRef('');
  const [filterText, setFilterText] = useState('');

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'd') {
        e.preventDefault();
        setOpen((o) => !o);
        ensurePatched();
      }
      if (e.key === 'Escape' && open) setOpen(false);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    ensurePatched();
    const sub = () => force((n) => n + 1);
    _listeners.add(sub);
    return () => {
      _listeners.delete(sub);
    };
  }, [open]);

  if (!open) return null;

  const events = filterText
    ? _buffer.filter(
        (e) =>
          e.prefix.toLowerCase().includes(filterText.toLowerCase()) ||
          e.body.toLowerCase().includes(filterText.toLowerCase()),
      )
    : _buffer;

  function exportJson() {
    const blob = new Blob([JSON.stringify(_buffer, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `cara-debug-${new Date().toISOString().slice(0, 19)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div
      className="fixed z-[100] top-0 right-0 h-dvh w-full sm:w-[22rem]
                 bg-slate-950/95 backdrop-blur border-l border-slate-700
                 text-slate-100 flex flex-col"
      role="dialog"
      aria-label="Debug overlay"
    >
      <header className="flex items-center justify-between p-3 border-b border-slate-700 shrink-0">
        <div>
          <p className="text-sm font-medium">🔧 Debug</p>
          <p className="text-[10px] text-slate-500">{_buffer.length} eventi · Ctrl+Shift+D</p>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={exportJson}
            className="text-xs rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-2 py-1"
          >
            Export
          </button>
          <button
            type="button"
            onClick={() => {
              _buffer.length = 0;
              force((n) => n + 1);
            }}
            className="text-xs rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-2 py-1"
          >
            Pulisci
          </button>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="text-slate-400 hover:text-slate-100 text-lg px-1"
            aria-label="Chiudi"
          >
            ✕
          </button>
        </div>
      </header>
      <input
        type="text"
        placeholder="filtra (cara-stt, cara-voice, …)"
        value={filterText}
        onChange={(e) => {
          filter.current = e.target.value;
          setFilterText(e.target.value);
        }}
        className="m-2 rounded-lg bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
      />
      <div className="flex-1 overflow-y-auto px-2 pb-2 font-mono text-[10px] leading-snug">
        {events.length === 0 ? (
          <p className="text-slate-500 p-2">
            Nessun evento. Apri /, parla, e gli eventi appariranno qui.
          </p>
        ) : (
          events
            .slice()
            .reverse()
            .map((e, i) => (
              <div key={i} className="border-b border-slate-800 py-1">
                <p className="text-slate-500">
                  {new Date(e.ts).toLocaleTimeString('it-IT', {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })}{' '}
                  <span className="text-emerald-400">{e.prefix}</span>
                </p>
                <p className="text-slate-300 break-all whitespace-pre-wrap">{e.body}</p>
              </div>
            ))
        )}
      </div>
    </div>
  );
}
