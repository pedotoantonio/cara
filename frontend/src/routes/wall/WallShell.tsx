// Wall shell — header with clock + avatar + meta, and a tab strip
// switching between Today / Week / Month sub-views. Public surface;
// no auth, no AppShell sidebar.

import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';

import { fetchSummary } from '../../api/wall';
import type { WallSummary } from '../../api/wall';
import { WallAvatarPanel } from '../../components/wall/WallAvatarPanel';
import { WallClock } from '../../components/wall/WallClock';
import { WallDeviceCam } from '../../components/wall/WallDeviceCam';
import { WallMic } from '../../components/wall/WallMic';
import { WeatherIcon } from '../../components/wall/WeatherIcon';

const TABS = [
  { to: '/wall', label: 'Oggi', end: true },
  { to: '/wall/week', label: 'Settimana', end: false },
  { to: '/wall/calendar', label: 'Mese', end: false },
  { to: '/wall/shopping', label: 'Spesa', end: false },
  { to: '/wall/services', label: 'Servizi', end: false },
  { to: '/wall/persons', label: 'Famiglia', end: false },
];

function HeaderMeta({ summary }: { summary: WallSummary | null }) {
  if (!summary) return <div className="text-fg-muted text-sm">Carico…</div>;
  const w = summary.weather;
  const presence = summary.presence;
  const inHouse = presence?.people?.map((p) => p.name).slice(0, 4).join(', ') || '';
  return (
    <div className="flex flex-col items-end gap-3 text-right">
      {w.available ? (
        <div className="flex items-center gap-3">
          <WeatherIcon slug={w.icon_slug} isDay={w.is_day} size={56} />
          <span>
            <span
              className="font-display"
              style={{ fontSize: 'clamp(28px, 3vw, 44px)', fontWeight: 300 }}
            >
              {Math.round(w.temperature_c ?? 0)}°
            </span>
            <span className="block text-fg-muted text-sm leading-tight">
              {w.label} · {w.city}
            </span>
          </span>
        </div>
      ) : (
        <span className="text-fg-muted text-sm">Meteo n/d</span>
      )}
      <div className="text-fg-soft text-sm">
        {presence.available ? (
          inHouse ? (
            <>
              <span className="text-fg-muted">In casa: </span>
              <span>{inHouse}</span>
            </>
          ) : (
            <span className="text-fg-muted">In casa: nessuno rilevato</span>
          )
        ) : (
          <span className="text-fg-muted">Presenza n/d</span>
        )}
      </div>
    </div>
  );
}

export function WallShell() {
  const [summary, setSummary] = useState<WallSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const location = useLocation();

  async function loadSummary() {
    try {
      const data = await fetchSummary();
      setSummary(data);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (cancelled) return;
      await loadSummary();
    }
    void load();
    const id = window.setInterval(load, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return (
    <div className="min-h-dvh w-full bg-bg text-fg overflow-hidden flex flex-col">
      <WallBackground />
      {/* Header */}
      <header className="px-8 pt-8 pb-4 grid grid-cols-3 items-center gap-6 z-10">
        <WallClock />
        <div className="flex flex-col items-center gap-3">
          <WallAvatarPanel size={156} />
          <WallMic />
          <WallDeviceCam />
        </div>
        <div className="flex justify-end">
          <HeaderMeta summary={summary} />
        </div>
      </header>

      {/* Tabs */}
      <nav
        className="flex justify-center gap-2 px-4 py-2 z-10"
        aria-label="Vista del wall"
      >
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              [
                'inline-flex items-center justify-center rounded-pill font-medium transition-colors',
                'px-6 py-2',
                isActive
                  ? 'bg-accent text-bg'
                  : 'bg-surface2 text-fg-soft hover:bg-surface2/80',
              ].join(' ')
            }
            style={{ fontSize: 'clamp(14px, 1.2vw, 18px)' }}
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      {/* Outlet — `min-h-0` is the magic that lets `flex-1` actually
          clamp the main panel to remaining viewport so children that
          rely on `overflow-y-auto` (calendar grid, week scroll) can
          compute heights instead of growing to fit content. */}
      <main className="flex-1 min-h-0 overflow-y-auto px-8 pb-8 z-10">
        {error && (
          <div className="text-alert text-center py-4">
            ⚠ {error}
          </div>
        )}
        <Outlet context={{ summary, location, refreshSummary: loadSummary }} />
      </main>
    </div>
  );
}

/** Subtle gradient background that shifts with time of day. Not animated
 *  per-frame; recomputed once per minute is enough. */
function WallBackground() {
  const [tone, setTone] = useState<string>(() => toneForHour(new Date().getHours()));
  useEffect(() => {
    const id = window.setInterval(() => {
      setTone(toneForHour(new Date().getHours()));
    }, 60_000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-0"
      style={{
        background: tone,
        opacity: 0.55,
        transition: 'background 4s ease',
      }}
    />
  );
}

function toneForHour(h: number): string {
  if (h < 6) return 'radial-gradient(ellipse at top, #1e293b 0%, #0f172a 70%)'; // night
  if (h < 9) return 'radial-gradient(ellipse at top, #fde68a 0%, transparent 70%)'; // dawn
  if (h < 17) return 'radial-gradient(ellipse at top, #bae6fd 0%, transparent 70%)'; // day
  if (h < 20) return 'radial-gradient(ellipse at top, #fdba74 0%, transparent 70%)'; // dusk
  return 'radial-gradient(ellipse at top, #312e81 0%, #0f172a 80%)';
}
