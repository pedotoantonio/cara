// Always-visible news ticker for the Wall — a thin strip that scrolls
// headline + source at the bottom of every Wall view. Pulls from the
// LAN-gated /api/v1/wall/news endpoint, refreshes every 5 minutes.
//
// Implementation: CSS-only marquee using `animation: ticker-x linear infinite`
// over a duplicated content row, so the loop is seamless. Pause on hover so
// the user can read a specific headline.

import { useEffect, useRef, useState } from 'react';

import { fetchWallNews } from '../../api/wall';
import type { WallNewsItem } from '../../api/wall';

const REFRESH_MS = 5 * 60_000;
const PIXELS_PER_SECOND = 60; // tweak speed

export function WallNewsTicker() {
  const [items, setItems] = useState<WallNewsItem[]>([]);
  const [error, setError] = useState(false);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [durationSec, setDurationSec] = useState<number>(120);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const r = await fetchWallNews({ limit: 25 });
        if (cancelled) return;
        setItems(r.items);
        setError(false);
      } catch {
        if (!cancelled) setError(true);
      }
    }
    void load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  // Compute animation duration so speed feels constant regardless of
  // headline count — measure rendered track width / px-per-second.
  useEffect(() => {
    if (!trackRef.current || items.length === 0) return;
    const w = trackRef.current.scrollWidth / 2; // half because content is duplicated
    if (w > 0) setDurationSec(Math.max(30, Math.round(w / PIXELS_PER_SECOND)));
  }, [items]);

  if (error || items.length === 0) {
    return null;
  }

  // Duplicate the content so the keyframe can translateX(0 → -50%) and
  // loop visually seamless.
  const rendered = (
    <div ref={trackRef} className="flex items-center gap-10 will-change-transform"
         style={{ animation: `ticker-x ${durationSec}s linear infinite` }}>
      {[0, 1].map((copy) => (
        <div key={copy} className="flex items-center gap-10 shrink-0">
          {items.map((it, i) => (
            <span key={`${copy}-${i}`} className="flex items-center gap-3 whitespace-nowrap">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-accent shrink-0" aria-hidden />
              <span className="text-fg/90">{it.title}</span>
              <span className="text-fg-muted text-sm">· {it.source}</span>
            </span>
          ))}
        </div>
      ))}
    </div>
  );

  return (
    <div
      className="shrink-0 h-10 w-full overflow-hidden bg-surface2/80 backdrop-blur-md border-t border-fg/8 z-20"
      aria-label="Notizie scorrevoli"
      style={{ ['--pause' as string]: 'paused' }}
    >
      <style>{`
        @keyframes ticker-x {
          from { transform: translateX(0); }
          to   { transform: translateX(-50%); }
        }
        .wall-ticker-track:hover > div { animation-play-state: paused; }
      `}</style>
      <div className="wall-ticker-track h-full flex items-center pl-6">{rendered}</div>
    </div>
  );
}
