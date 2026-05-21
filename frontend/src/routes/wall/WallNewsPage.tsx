// Wall news page — sequential reader.
//
// Shows one news at a time, full-screen card with title + source +
// summary + published time. After a reading duration (auto-computed
// from text length, min 8s, max 30s), advances to the next item.
// Loops back to the first when the list is consumed. Manual controls
// for pause / prev / next so the family can linger on something.

import { useEffect, useMemo, useRef, useState } from 'react';

import { fetchWallNews } from '../../api/wall';
import type { WallNewsItem } from '../../api/wall';

const REFRESH_MS = 10 * 60_000;
const MIN_DWELL_MS = 8_000;
const MAX_DWELL_MS = 30_000;
// rough Italian reading speed: 180 words/min ≈ 3 wps ≈ 18 chars/sec
const CHARS_PER_SEC = 18;

function dwellMs(item: WallNewsItem): number {
  const len = (item.title?.length ?? 0) + (item.summary?.length ?? 0);
  const ms = Math.round((len / CHARS_PER_SEC) * 1000);
  return Math.max(MIN_DWELL_MS, Math.min(MAX_DWELL_MS, ms));
}

function timeAgo(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const mins = Math.floor((Date.now() - d.getTime()) / 60_000);
  if (mins < 1) return 'pochi secondi fa';
  if (mins < 60) return `${mins} min fa`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} h fa`;
  const days = Math.floor(hrs / 24);
  return `${days} g fa`;
}

const CATEGORIES = [
  { id: 'all', label: 'Tutte' },
  { id: 'italia', label: 'Italia' },
  { id: 'mondo', label: 'Mondo' },
  { id: 'economia', label: 'Economia' },
  { id: 'tech', label: 'Tech' },
  { id: 'sport', label: 'Sport' },
];

export function WallNewsPage() {
  const [items, setItems] = useState<WallNewsItem[]>([]);
  const [category, setCategory] = useState<string>('all');
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [progress, setProgress] = useState(0); // 0..1 for the bar
  const progressTickRef = useRef<number | null>(null);
  const advanceTimerRef = useRef<number | null>(null);

  // Fetch on mount + on category change + periodic refresh
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const r = await fetchWallNews({ category, limit: 25 });
        if (cancelled) return;
        setItems(r.items);
        setError(null);
        // keep index stable if possible, else reset
        setIndex((i) => (r.items.length === 0 ? 0 : Math.min(i, r.items.length - 1)));
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    }
    void load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [category]);

  // Auto-advance + progress bar
  useEffect(() => {
    if (advanceTimerRef.current !== null) {
      window.clearTimeout(advanceTimerRef.current);
      advanceTimerRef.current = null;
    }
    if (progressTickRef.current !== null) {
      window.clearInterval(progressTickRef.current);
      progressTickRef.current = null;
    }
    setProgress(0);
    if (paused || items.length === 0) return;

    const total = dwellMs(items[index]);
    const startedAt = Date.now();
    progressTickRef.current = window.setInterval(() => {
      const elapsed = Date.now() - startedAt;
      setProgress(Math.min(1, elapsed / total));
    }, 200);
    advanceTimerRef.current = window.setTimeout(() => {
      setIndex((i) => (items.length === 0 ? 0 : (i + 1) % items.length));
    }, total);

    return () => {
      if (advanceTimerRef.current !== null) window.clearTimeout(advanceTimerRef.current);
      if (progressTickRef.current !== null) window.clearInterval(progressTickRef.current);
    };
  }, [items, index, paused]);

  const current = useMemo(() => items[index] ?? null, [items, index]);

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center text-center py-24">
        <p className="text-alert text-2xl mb-2">⚠ Impossibile caricare le notizie</p>
        <p className="text-fg-muted text-sm">{error}</p>
      </div>
    );
  }

  if (!current) {
    return (
      <div className="flex flex-col items-center justify-center text-center py-24">
        <p className="text-fg-muted text-xl">Nessuna notizia per ora.</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col gap-4">
      {/* Category strip */}
      <div className="flex flex-wrap gap-2 justify-center">
        {CATEGORIES.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => { setCategory(c.id); setIndex(0); }}
            className={[
              'px-4 py-1.5 rounded-pill text-sm transition-colors',
              category === c.id
                ? 'bg-accent text-bg'
                : 'bg-surface2 text-fg-soft hover:bg-surface2/80',
            ].join(' ')}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* News card */}
      <article
        className="flex-1 min-h-0 rounded-3xl bg-surface1/70 backdrop-blur-sm ring-1 ring-fg/8 px-10 py-8 flex flex-col"
      >
        <header className="flex items-center justify-between gap-4 mb-6 text-fg-muted text-sm">
          <span className="font-medium text-fg-soft">{current.source}</span>
          <span>{timeAgo(current.published)} · {index + 1}/{items.length}</span>
        </header>

        <h2
          className="font-display leading-tight text-fg mb-6"
          style={{ fontSize: 'clamp(28px, 3.4vw, 56px)', fontWeight: 500 }}
        >
          {current.title}
        </h2>

        <p
          className="text-fg-soft leading-relaxed"
          style={{ fontSize: 'clamp(18px, 1.6vw, 26px)' }}
        >
          {current.summary || ' '}
        </p>

        {/* Spacer + controls */}
        <div className="mt-auto pt-6 flex items-center gap-4">
          <button
            type="button"
            onClick={() => setIndex((i) => (items.length === 0 ? 0 : (i - 1 + items.length) % items.length))}
            aria-label="Notizia precedente"
            className="px-4 py-2 rounded-pill bg-surface2 text-fg-soft hover:bg-surface2/80 transition"
          >
            ←
          </button>
          <button
            type="button"
            onClick={() => setPaused((p) => !p)}
            aria-label={paused ? 'Riprendi' : 'Pausa'}
            className="px-5 py-2 rounded-pill bg-accent text-bg hover:bg-accent/90 transition min-w-[110px]"
          >
            {paused ? '▶ Riprendi' : '⏸ Pausa'}
          </button>
          <button
            type="button"
            onClick={() => setIndex((i) => (items.length === 0 ? 0 : (i + 1) % items.length))}
            aria-label="Notizia successiva"
            className="px-4 py-2 rounded-pill bg-surface2 text-fg-soft hover:bg-surface2/80 transition"
          >
            →
          </button>
          <div className="flex-1 h-1.5 rounded-full bg-fg/10 overflow-hidden">
            <div
              className="h-full bg-accent transition-[width] duration-200"
              style={{ width: `${Math.round(progress * 100)}%` }}
              aria-hidden
            />
          </div>
        </div>
      </article>
    </div>
  );
}
