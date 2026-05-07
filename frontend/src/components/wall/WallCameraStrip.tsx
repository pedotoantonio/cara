// Rotating camera strip for the Wall — fetches the list of online,
// presence-relevant cameras from /api/v1/wall/cameras and shows a
// large featured snapshot that auto-rotates every 8s, with a row of
// small thumbnails below.
//
// Snapshots refresh every 6s by busting the URL query param (the
// backend caches 3s, so we get a fresh-enough frame). Click a
// thumbnail to lock it as featured (auto-rotation pauses for 30s).

import { useEffect, useMemo, useRef, useState } from 'react';

import { fetchCameras, snapshotUrl } from '../../api/wall';
import type { WallCamera } from '../../api/wall';

const ROTATE_MS = 8_000;
const REFRESH_MS = 6_000;
const PAUSE_AFTER_CLICK_MS = 30_000;

function relTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (!t) return '';
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (sec < 60) return `${sec}s fa`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min fa`;
  return `${Math.round(min / 60)}h fa`;
}

export function WallCameraStrip() {
  const [cams, setCams] = useState<WallCamera[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [activeIdx, setActiveIdx] = useState(0);
  const [bust, setBust] = useState<number>(() => Date.now());
  const pausedUntilRef = useRef<number>(0);

  // Load camera list, refresh every 60s
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const list = await fetchCameras();
        if (cancelled) return;
        setCams(list);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError((e as Error).message);
      }
    }
    void load();
    const id = window.setInterval(load, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  // Image refresh tick — bust query param so all <img> refetch
  useEffect(() => {
    const id = window.setInterval(() => setBust(Date.now()), REFRESH_MS);
    return () => window.clearInterval(id);
  }, []);

  // Auto-rotation
  useEffect(() => {
    if (cams.length <= 1) return;
    const id = window.setInterval(() => {
      if (Date.now() < pausedUntilRef.current) return;
      setActiveIdx((i) => (i + 1) % cams.length);
    }, ROTATE_MS);
    return () => window.clearInterval(id);
  }, [cams.length]);

  const featured = cams[activeIdx] ?? null;
  const featuredSrc = useMemo(
    () => (featured ? snapshotUrl(featured.id, bust) : null),
    [featured, bust],
  );

  if (error) {
    return (
      <div className="rounded-xl bg-surface2/40 px-4 py-3 text-fg-muted text-sm">
        Telecamere non raggiungibili: {error}
      </div>
    );
  }
  if (cams.length === 0) {
    return null; // no online cameras → strip simply hides
  }

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <h2
          className="font-display text-fg-soft"
          style={{ fontSize: 'clamp(20px, 1.8vw, 28px)' }}
        >
          Telecamere
        </h2>
        <span className="text-fg-muted text-xs">
          {cams.length} {cams.length === 1 ? 'attiva' : 'attive'}
          {featured && ` · aggiornata ${relTime(featured.last_seen)}`}
        </span>
      </div>

      {/* Featured */}
      <div
        className="relative rounded-xl overflow-hidden bg-black/40"
        style={{ aspectRatio: '16 / 9', maxHeight: '46vh' }}
      >
        {featuredSrc && featured ? (
          <img
            key={featured.id /* re-mount on swap so the crossfade triggers */}
            src={featuredSrc}
            alt={featured.label}
            className="absolute inset-0 w-full h-full object-cover animate-rise"
            loading="eager"
            onError={(e) => {
              // Hide a frame that 502s instead of breaking the layout.
              (e.currentTarget as HTMLImageElement).style.opacity = '0';
            }}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-fg-muted">
            Nessuna telecamera disponibile
          </div>
        )}
        {featured && (
          <div className="absolute bottom-0 left-0 right-0 px-4 py-2 bg-gradient-to-t from-black/70 to-transparent text-white">
            <div className="flex items-baseline justify-between gap-3">
              <span
                className="font-display"
                style={{ fontSize: 'clamp(18px, 1.6vw, 24px)' }}
              >
                {featured.label}
              </span>
              <span className="text-xs opacity-80">
                {featured.area && (
                  <span className="mr-2 opacity-60">{featured.area}</span>
                )}
                {relTime(featured.last_seen)}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Thumbnails */}
      {cams.length > 1 && (
        <div className="grid grid-flow-col auto-cols-fr gap-2">
          {cams.map((c, i) => (
            <button
              key={c.id}
              type="button"
              onClick={() => {
                setActiveIdx(i);
                pausedUntilRef.current = Date.now() + PAUSE_AFTER_CLICK_MS;
              }}
              className={[
                'relative rounded-md overflow-hidden bg-black/40 transition-all',
                'border-2',
                i === activeIdx
                  ? 'border-accent'
                  : 'border-transparent opacity-70 hover:opacity-100',
              ].join(' ')}
              style={{ aspectRatio: '16 / 9' }}
              title={c.label}
            >
              <img
                src={snapshotUrl(c.id, bust)}
                alt={c.label}
                className="w-full h-full object-cover"
                loading="lazy"
                onError={(e) => {
                  (e.currentTarget as HTMLImageElement).style.opacity = '0';
                }}
              />
              <span
                className="absolute bottom-0 left-0 right-0 px-1.5 py-0.5 bg-black/60 text-white text-2xs truncate"
              >
                {c.label}
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
