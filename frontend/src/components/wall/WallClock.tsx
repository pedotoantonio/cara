// Big clock + Italian-formatted long date for the Wall header. Updates
// every 1s (only re-renders on minute rollover for the time string).

import { useEffect, useState } from 'react';

const WEEKDAYS = [
  'domenica', 'lunedì', 'martedì', 'mercoledì',
  'giovedì', 'venerdì', 'sabato',
];
const MONTHS = [
  'gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
  'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre',
];

function fmtTime(d: Date): string {
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  return `${h}:${m}`;
}

function fmtDate(d: Date): string {
  return `${WEEKDAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export function WallClock() {
  const [now, setNow] = useState<Date>(() => new Date());

  useEffect(() => {
    // Tick every second so we catch the minute rollover quickly. The
    // component itself renders only the minute, so React skips paint
    // when nothing changed.
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div className="flex flex-col">
      <span
        className="font-display text-fg leading-none tracking-tight"
        style={{ fontSize: 'clamp(64px, 8vw, 132px)', fontWeight: 200 }}
      >
        {fmtTime(now)}
      </span>
      <span
        className="font-display text-fg-soft mt-2 first-letter:capitalize"
        style={{ fontSize: 'clamp(18px, 1.6vw, 26px)' }}
      >
        {fmtDate(now)}
      </span>
    </div>
  );
}
