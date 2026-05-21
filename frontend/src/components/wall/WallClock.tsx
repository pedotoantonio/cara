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
    // min-h matches the avatar (156 px in the header); justify-center
    // keeps the time digits at the same Y as the avatar centre. Without
    // it the clock was anchored to the top of its grid cell, looking
    // visually disconnected from the rest of the header row.
    // On tablets+ we anchor the clock to a 156-px min-height so its
    // baseline lines up with the centre of the header avatar. On
    // mobile the avatar is much smaller and the grid collapses, so the
    // rigid min-h is dropped. The time `clamp(...)` now has a 52 px
    // floor — readable on 360px without dominating the screen.
    <div className="flex flex-col justify-center md:min-h-[156px]">
      <span
        className="font-display text-fg leading-none tracking-tight"
        style={{ fontSize: 'clamp(52px, 9vw, 156px)', fontWeight: 200 }}
      >
        {fmtTime(now)}
      </span>
      <span
        className="font-display text-fg-soft mt-1 sm:mt-2 first-letter:capitalize"
        style={{ fontSize: 'clamp(13px, 1.6vw, 26px)' }}
      >
        {fmtDate(now)}
      </span>
    </div>
  );
}
