// WallDayStrip — strip slim sempre visibile sotto le tab del Wall.
// Mostra: santo del giorno · fase lunare · alba/tramonto · proverbio.
//
// Auto-refresh ogni 6h. Fallisce gracefully (ritorna null) se l'API
// è offline o l'utente non è ancora autenticato.

import { useEffect, useState } from 'react';

interface DayInfo {
  iso: string;
  day_name_it: string;
  long_format_it: string;
  is_holiday: boolean;
  holiday_name: string | null;
  saint: string | null;
  moon_phase: string;
  moon_phase_emoji: string;
  sunrise: string | null;
  sunset: string | null;
  proverb: string;
  countdowns: Array<{ label: string; emoji: string; days_to: number }>;
}

export function WallDayStrip() {
  const [info, setInfo] = useState<DayInfo | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const r = await fetch('/api/v1/calendar/day-info', {
          credentials: 'include',
        });
        if (!r.ok) {
          // Wall LAN-only auth fallback: prova LAN auto-login se 401
          if (r.status === 401) {
            await fetch('/api/v1/auth/lan-login', {
              method: 'POST',
              credentials: 'include',
            });
            const r2 = await fetch('/api/v1/calendar/day-info', {
              credentials: 'include',
            });
            if (r2.ok && !cancelled) {
              setInfo(await r2.json());
              return;
            }
          }
          throw new Error(`HTTP ${r.status}`);
        }
        if (!cancelled) setInfo(await r.json());
      } catch (e) {
        if (!cancelled) setErr(String(e));
      }
    }
    void load();
    // Refresh ogni 6h
    const t = window.setInterval(load, 6 * 60 * 60 * 1000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, []);

  if (err || !info) return null;

  const nextEvent = info.countdowns[0];

  return (
    <div
      className="px-3 sm:px-6 py-2 mx-auto max-w-7xl text-fg-soft
                 flex items-center justify-center gap-3 sm:gap-5
                 flex-wrap text-sm sm:text-base"
      style={{ fontSize: 'clamp(13px, 1vw, 17px)' }}
      role="complementary"
      aria-label="Info del giorno"
    >
      {info.is_holiday && info.holiday_name && (
        <span className="px-2.5 py-0.5 rounded-pill bg-accent/15 text-accent font-medium">
          🎉 {info.holiday_name}
        </span>
      )}
      {info.saint && (
        <span title="Santo del giorno">
          <span className="text-fg-muted mr-1">✝</span>
          {info.saint}
        </span>
      )}
      <span title={`Luna ${info.moon_phase}`}>
        {info.moon_phase_emoji} {info.moon_phase}
      </span>
      {info.sunrise && info.sunset && (
        <span title="Alba / Tramonto" className="font-mono">
          ☀️ {info.sunrise} → {info.sunset}
        </span>
      )}
      {nextEvent && nextEvent.days_to > 0 && nextEvent.days_to <= 30 && (
        <span className="text-fg-muted">
          {nextEvent.emoji} {nextEvent.label} fra {nextEvent.days_to} giorni
        </span>
      )}
      {info.proverb && (
        <span className="italic text-fg-muted hidden md:inline">
          "{info.proverb}"
        </span>
      )}
    </div>
  );
}
