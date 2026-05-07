// Monthly grid view for the Wall — 7 cols × 6 rows wall-calendar style.

import { useEffect, useState } from 'react';

import { fetchCalendar } from '../../api/wall';
import type { WallCalendar, WallDay, WallItem } from '../../api/wall';
import {
  WallDayCell,
  WallDayDetailModal,
} from '../../components/wall/WallDayCell';
import { WallItemDetail } from '../../components/wall/WallItemDetail';

const MONTH_LABELS = [
  'gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
  'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre',
];
const HEADER_DAYS = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'];

export function WallCalendarPage() {
  const today = new Date();
  const [year, setYear] = useState<number>(today.getFullYear());
  const [month, setMonth] = useState<number>(today.getMonth() + 1);
  const [data, setData] = useState<WallCalendar | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<WallDay | null>(null);
  const [picked, setPicked] = useState<WallItem | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    async function load() {
      try {
        const d = await fetchCalendar(year, month);
        if (!cancelled) setData(d);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    }
    void load();
    const id = window.setInterval(load, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [year, month, tick]);

  function shift(delta: number) {
    let y = year;
    let m = month + delta;
    if (m < 1) {
      m = 12;
      y -= 1;
    } else if (m > 12) {
      m = 1;
      y += 1;
    }
    setYear(y);
    setMonth(m);
  }

  function jumpToToday() {
    setYear(today.getFullYear());
    setMonth(today.getMonth() + 1);
  }

  return (
    <div className="flex flex-col gap-4 mt-2">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => shift(-1)}
            className="rounded-pill bg-surface2 px-4 py-2 text-fg-soft hover:bg-surface2/80"
            aria-label="Mese precedente"
          >
            ‹
          </button>
          <button
            type="button"
            onClick={() => shift(+1)}
            className="rounded-pill bg-surface2 px-4 py-2 text-fg-soft hover:bg-surface2/80"
            aria-label="Mese successivo"
          >
            ›
          </button>
          <button
            type="button"
            onClick={jumpToToday}
            className="rounded-pill bg-surface2 px-4 py-2 text-fg-soft hover:bg-surface2/80 text-sm"
          >
            Oggi
          </button>
        </div>
        <h2
          className="font-display text-fg first-letter:capitalize"
          style={{ fontSize: 'clamp(28px, 3vw, 44px)', fontWeight: 300 }}
        >
          {MONTH_LABELS[month - 1]} {year}
        </h2>
        <div className="w-32" /> {/* spacer for symmetry */}
      </div>

      {error && <div className="text-alert text-center py-2">⚠ {error}</div>}

      {/* Weekday header */}
      <div className="grid grid-cols-7 gap-2">
        {HEADER_DAYS.map((d, i) => (
          <div
            key={d}
            className={[
              'text-center font-medium pb-1 border-b border-surface2',
              i >= 5 ? 'text-fg-muted' : 'text-fg-soft',
            ].join(' ')}
            style={{ fontSize: 'clamp(13px, 1vw, 16px)' }}
          >
            {d}
          </div>
        ))}
      </div>

      {/* Grid */}
      {!data ? (
        <div className="text-fg-muted text-center py-8 animate-breathe">
          Carico il calendario…
        </div>
      ) : (
        <div className="grid grid-cols-7 gap-2">
          {data.days.map((day) => (
            <WallDayCell
              key={day.date}
              day={day}
              monthVisible={day.in_month !== false}
              onShowMore={setDetail}
              onPickItem={setPicked}
            />
          ))}
        </div>
      )}

      {detail && (
        <WallDayDetailModal
          day={detail}
          onClose={() => setDetail(null)}
          onPickItem={setPicked}
        />
      )}

      {picked && data && (
        <WallItemDetail
          item={picked}
          family={data.family}
          onClose={() => setPicked(null)}
          onChanged={() => setTick((t) => t + 1)}
        />
      )}
    </div>
  );
}
