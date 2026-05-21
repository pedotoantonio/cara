// Week view — 7 columns Mon→Sun for the current (or navigated) week.
// Items shown as stacked chips per-day, owner-colored.

import { useEffect, useMemo, useState } from 'react';

import { fetchWeek } from '../../api/wall';
import type { WallWeek, WallDay, WallItem } from '../../api/wall';
import { OwnerChip } from '../../components/wall/OwnerChip';
import { WallItemDetail } from '../../components/wall/WallItemDetail';

const WEEKDAYS_FULL = [
  'lunedì', 'martedì', 'mercoledì', 'giovedì',
  'venerdì', 'sabato', 'domenica',
];

function mondayOf(d: Date): Date {
  const dow = (d.getDay() + 6) % 7; // Mon=0 … Sun=6
  const out = new Date(d);
  out.setHours(0, 0, 0, 0);
  out.setDate(out.getDate() - dow);
  return out;
}

function fmtTimeShort(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  if (d.getHours() === 0 && d.getMinutes() === 0) return '';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const da = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${da}`;
}

function ItemChip({
  item,
  onPick,
}: {
  item: WallItem;
  onPick: (item: WallItem) => void;
}) {
  const time = fmtTimeShort(item.start ?? item.due_date);
  const isDone = item.kind === 'task' && item.done;
  return (
    <button
      type="button"
      onClick={() => onPick(item)}
      className={[
        'w-full text-left rounded-md px-2 py-1.5 text-sm leading-tight',
        'hover:brightness-110 transition',
        isDone ? 'opacity-50' : '',
      ].join(' ')}
      style={{
        background: `${item.owner?.color ?? '#94a3b8'}1f`,
        borderLeft: `4px solid ${item.owner?.color ?? '#94a3b8'}`,
      }}
      title={`${item.title}${item.owner ? ` · ${item.owner.display_name}` : ''}`}
    >
      <div className="flex items-baseline gap-2 min-w-0">
        {time && (
          <span className="font-mono text-xs text-fg-muted flex-shrink-0">
            {time}
          </span>
        )}
        <span
          className={[
            'truncate flex-1',
            isDone ? 'line-through' : '',
          ].join(' ')}
        >
          {item.title}
        </span>
      </div>
      {item.owner && (
        <div className="mt-1 flex items-center gap-1.5">
          <OwnerChip user={item.owner} variant="dot" />
          <span className="text-2xs text-fg-muted">
            {item.owner.display_name}
          </span>
        </div>
      )}
    </button>
  );
}

function DayColumn({
  day,
  onPick,
}: {
  day: WallDay;
  onPick: (item: WallItem) => void;
}) {
  const date = new Date(day.date);
  const dow = (date.getDay() + 6) % 7;
  return (
    <div className="flex flex-col gap-2">
      <div
        className={[
          'border-b border-surface2 pb-2 text-center',
          day.is_today ? 'text-accent' : day.is_holiday ? 'text-rose-500' : 'text-fg-soft',
        ].join(' ')}
      >
        <div
          className="font-medium first-letter:capitalize"
          style={{ fontSize: 'clamp(14px, 1.1vw, 18px)' }}
        >
          {WEEKDAYS_FULL[dow]}
        </div>
        <div
          className={[
            'font-display',
            day.is_today
              ? 'inline-flex items-center justify-center bg-accent text-bg rounded-full w-9 h-9 mt-1 mx-auto'
              : '',
          ].join(' ')}
          style={{ fontSize: day.is_today ? 18 : 22, fontWeight: 300 }}
        >
          {date.getDate()}
        </div>
      </div>
      <div className="flex flex-col gap-1.5 flex-1 min-h-0 sm:min-h-[120px]">
        {day.items.length === 0 && (
          <span className="text-fg-muted text-xs italic text-center mt-2">
            —
          </span>
        )}
        {day.items.map((it) => (
          <ItemChip key={`${it.kind}-${it.id}`} item={it} onPick={onPick} />
        ))}
      </div>
    </div>
  );
}

export function WallWeekPage() {
  const [start, setStart] = useState<Date>(() => mondayOf(new Date()));
  const [data, setData] = useState<WallWeek | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<WallItem | null>(null);
  const [tick, setTick] = useState(0);

  const startISO = useMemo(() => isoDate(start), [start]);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    async function load() {
      try {
        const w = await fetchWeek(startISO);
        if (!cancelled) setData(w);
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
  }, [startISO, tick]);

  function shift(deltaDays: number) {
    const next = new Date(start);
    next.setDate(next.getDate() + deltaDays);
    setStart(mondayOf(next));
  }

  function jumpToThisWeek() {
    setStart(mondayOf(new Date()));
  }

  const endLabel = (() => {
    const end = new Date(start);
    end.setDate(end.getDate() + 6);
    return end.toLocaleDateString('it-IT', { day: 'numeric', month: 'long' });
  })();
  const startLabel = start.toLocaleDateString('it-IT', { day: 'numeric', month: 'long' });

  return (
    <div className="flex flex-col gap-3 sm:gap-4 mt-2">
      {/* Header — wraps on mobile so navigation buttons + label fit
          without horizontal scroll. */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 sm:gap-3">
          <button
            type="button"
            onClick={() => shift(-7)}
            className="rounded-pill bg-surface2 px-3 sm:px-4 py-1.5 sm:py-2 text-fg-soft hover:bg-surface2/80"
            aria-label="Settimana precedente"
          >
            ‹
          </button>
          <button
            type="button"
            onClick={() => shift(+7)}
            className="rounded-pill bg-surface2 px-3 sm:px-4 py-1.5 sm:py-2 text-fg-soft hover:bg-surface2/80"
            aria-label="Settimana successiva"
          >
            ›
          </button>
          <button
            type="button"
            onClick={jumpToThisWeek}
            className="rounded-pill bg-surface2 px-3 sm:px-4 py-1.5 sm:py-2 text-fg-soft hover:bg-surface2/80 text-xs sm:text-sm"
          >
            Oggi
          </button>
        </div>
        <h2
          className="font-display text-fg w-full sm:w-auto order-first sm:order-none text-center sm:text-left"
          style={{ fontSize: 'clamp(18px, 2vw, 28px)', fontWeight: 300 }}
        >
          {startLabel} – {endLabel}
        </h2>
        <div className="hidden sm:block sm:w-32" />
      </div>

      {error && <div className="text-alert text-center py-2">⚠ {error}</div>}

      {!data ? (
        <div className="text-fg-muted text-center py-8 animate-breathe">
          Carico la settimana…
        </div>
      ) : (
        // Phone: single column stacked (each day full-width readable).
        // Small tablet: 2 cols. Tablet: 4 cols. Desktop: 7 cols.
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2 sm:gap-3">
          {data.days.map((day) => (
            <DayColumn key={day.date} day={day} onPick={setPicked} />
          ))}
        </div>
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
