// Wall shell — header with clock + avatar + meta, and a tab strip
// switching between Today / Week / Month sub-views. Public surface;
// no auth, no AppShell sidebar.

import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';

import { fetchSummary } from '../../api/wall';
import type { WallSummary } from '../../api/wall';
import { WallAvatarPanel } from '../../components/wall/WallAvatarPanel';
import { WallClock } from '../../components/wall/WallClock';
import { WallMic } from '../../components/wall/WallMic';
import { WallNewsTicker } from '../../components/wall/WallNewsTicker';
import { WeatherIcon } from '../../components/wall/WeatherIcon';

const TABS = [
  { to: '/wall', label: 'Oggi', end: true },
  { to: '/wall/week', label: 'Settimana', end: false },
  { to: '/wall/calendar', label: 'Mese', end: false },
  { to: '/wall/shopping', label: 'Spesa', end: false },
  { to: '/wall/news', label: 'News', end: false },
  { to: '/wall/services', label: 'Servizi', end: false },
];

function HeaderMeta({ summary }: { summary: WallSummary | null }) {
  if (!summary) return <div className="text-fg-muted text-sm">Carico…</div>;
  const w = summary.weather;
  const presence = summary.presence;
  const inHouse = presence?.people?.map((p) => p.name).slice(0, 4).join(', ') || '';
  return (
    // Left-aligned on mobile, right-aligned on tablets+ to balance the
    // 3-column header grid.
    <div className="flex flex-col items-start md:items-end gap-2 md:gap-3 text-left md:text-right w-full">
      {w.available ? (
        <div className="flex items-center gap-2 md:gap-3">
          <WeatherIcon slug={w.icon_slug} isDay={w.is_day} size={44} />
          <span>
            <span
              className="font-display"
              style={{ fontSize: 'clamp(24px, 3vw, 44px)', fontWeight: 300 }}
            >
              {Math.round(w.temperature_c ?? 0)}°
            </span>
            <span className="block text-fg-muted text-xs md:text-sm leading-tight">
              {w.label} · {w.city}
            </span>
          </span>
        </div>
      ) : (
        <span className="text-fg-muted text-sm">Meteo n/d</span>
      )}
      <div className="text-fg-soft text-xs md:text-sm">
        {presence.available ? (
          inHouse ? (
            <>
              <span className="text-fg-muted">In casa: </span>
              <span>{inHouse}</span>
            </>
          ) : (
            <span className="text-fg-muted">In casa: nessuno</span>
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

      {/* Header — single-column stack on phones, 3-col grid on tablets+.
          On mobile we render the meta inline under the clock instead of
          in a right-rail so we don't waste vertical space and the avatar
          can sit centred under everything. */}
      <header
        className="px-4 sm:px-6 lg:px-8 pt-4 sm:pt-6 lg:pt-8 pb-3 z-10
                   flex flex-col gap-3
                   md:grid md:grid-cols-3 md:items-center md:gap-6"
      >
        <WallClock />
        <div className="flex flex-col items-center gap-2 sm:gap-3 order-3 md:order-none">
          {/* Avatar shrinks on phones — 96 px keeps it visible without
              dominating a 360 px viewport; 156 px reserved for tablets+. */}
          <div className="hidden md:block">
            <WallAvatarPanel size={156} />
          </div>
          <div className="md:hidden">
            <WallAvatarPanel size={96} />
          </div>
          <WallMic />
        </div>
        <div className="flex md:justify-end order-2 md:order-none">
          <HeaderMeta summary={summary} />
        </div>
      </header>

      {/* Tabs — horizontal scroll on phones so all 6 fit without
          wrapping; centred pill bar on tablets+. */}
      <nav
        className="px-2 sm:px-4 py-2 z-10 overflow-x-auto no-scrollbar"
        aria-label="Vista del wall"
      >
        <div
          className="inline-flex gap-1 p-1 sm:p-1.5 rounded-pill bg-surface1/70
                     backdrop-blur-md ring-1 ring-fg/8 shadow-sm
                     mx-auto"
          style={{ minWidth: 'fit-content' }}
        >
          {TABS.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.end}
              className={({ isActive }) =>
                [
                  'inline-flex items-center justify-center rounded-pill font-medium transition-all duration-200',
                  'px-3 sm:px-5 py-1.5 sm:py-2 whitespace-nowrap',
                  isActive
                    ? 'bg-accent text-bg shadow-md scale-[1.02]'
                    : 'text-fg-soft hover:bg-surface2/60 hover:text-fg',
                ].join(' ')
              }
              style={{ fontSize: 'clamp(13px, 1.1vw, 18px)' }}
            >
              {tab.label}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* Outlet — `min-h-0` is the magic that lets `flex-1` actually
          clamp the main panel to remaining viewport so children that
          rely on `overflow-y-auto` (calendar grid, week scroll) can
          compute heights instead of growing to fit content. */}
      <main className="flex-1 min-h-0 overflow-y-auto px-3 sm:px-6 lg:px-8 pb-4 z-10">
        {error && (
          <div className="text-alert text-center py-4">
            ⚠ {error}
          </div>
        )}
        <Outlet context={{ summary, location, refreshSummary: loadSummary }} />
      </main>

      {/* Persistent scrolling news ticker — visible across all Wall views */}
      <WallNewsTicker />
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
