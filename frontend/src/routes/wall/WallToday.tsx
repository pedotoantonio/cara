// Today view — chronological feed of events+tasks for today, plus an
// upcoming-3-days strip and an "open tasks" overflow at the bottom.

import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';

import type { WallItem, WallSummary } from '../../api/wall';
import { OwnerChip } from '../../components/wall/OwnerChip';
import { WallCameraStrip } from '../../components/wall/WallCameraStrip';
import { WallItemDetail } from '../../components/wall/WallItemDetail';

interface OutletCtx {
  summary: WallSummary | null;
  refreshSummary?: () => void;
}

const WEEKDAYS_SHORT = ['Dom', 'Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab'];
const MONTHS_SHORT = [
  'gen', 'feb', 'mar', 'apr', 'mag', 'giu',
  'lug', 'ago', 'set', 'ott', 'nov', 'dic',
];

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  // Heuristic: tasks with due_date set to midnight are "no exact time".
  if (d.getHours() === 0 && d.getMinutes() === 0) return '';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function fmtShortDate(iso: string): string {
  const d = new Date(iso);
  return `${WEEKDAYS_SHORT[d.getDay()]} ${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
}

function ItemRow({
  item,
  onPick,
}: {
  item: WallItem;
  onPick: (it: WallItem) => void;
}) {
  const time = fmtTime(item.start ?? item.due_date ?? null);
  const isDone = item.kind === 'task' && Boolean(item.done);
  const isOverdue = (() => {
    const ts = item.start ?? item.due_date;
    if (!ts) return false;
    return !isDone && new Date(ts).getTime() < Date.now() - 5 * 60_000;
  })();

  return (
    <button
      type="button"
      onClick={() => onPick(item)}
      className={[
        'w-full text-left flex items-center gap-4 py-3 px-4 rounded-lg',
        'border-l-4 bg-surface2/40 hover:bg-surface2/60 transition-colors',
        isDone ? 'opacity-50' : '',
      ].join(' ')}
      style={{ borderLeftColor: item.owner?.color ?? '#94a3b8' }}
    >
      <span
        className="font-mono text-fg-soft flex-shrink-0 w-14"
        style={{ fontSize: 'clamp(14px, 1.2vw, 18px)' }}
      >
        {time || '—'}
      </span>
      <span
        className="flex-shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded text-2xs uppercase tracking-wide"
        style={{
          background: item.kind === 'event' ? '#ddd6fe' : '#fde68a',
          color: '#0f172a',
        }}
      >
        {item.kind === 'event' ? 'evento' : 'task'}
      </span>
      <span
        className={[
          'flex-1 min-w-0 truncate',
          isDone ? 'line-through' : '',
          isOverdue ? 'text-alert' : 'text-fg',
        ].join(' ')}
        style={{ fontSize: 'clamp(16px, 1.4vw, 22px)' }}
        title={item.title}
      >
        {item.title}
      </span>
      <OwnerChip user={item.owner} variant="full" />
    </button>
  );
}

function UpcomingCard({
  date,
  count,
  preview,
}: {
  date: string;
  count: number;
  preview: WallItem[];
}) {
  return (
    <div className="rounded-xl bg-surface2/50 p-4 flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <span
          className="font-display font-medium text-fg first-letter:capitalize"
          style={{ fontSize: 'clamp(16px, 1.4vw, 20px)' }}
        >
          {fmtShortDate(date)}
        </span>
        <span className="text-fg-muted text-sm">
          {count} {count === 1 ? 'voce' : 'voci'}
        </span>
      </div>
      {preview.length === 0 ? (
        <span className="text-fg-muted text-sm italic">Niente in calendario</span>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {preview.map((it) => (
            <li
              key={`${it.kind}-${it.id}`}
              className="flex items-center gap-2 text-sm"
            >
              <OwnerChip user={it.owner} variant="dot" />
              <span className="text-fg-soft truncate flex-1" title={it.title}>
                {fmtTime(it.start ?? it.due_date) && (
                  <span className="font-mono text-xs text-fg-muted mr-1.5">
                    {fmtTime(it.start ?? it.due_date)}
                  </span>
                )}
                {it.title}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PendingByOwner({
  rows,
}: {
  rows: WallSummary['pending_by_owner'];
}) {
  if (!rows.length) return null;
  return (
    <div className="rounded-xl bg-surface2/40 px-4 py-3 flex flex-wrap items-center gap-3">
      <span className="text-fg-muted text-sm">Aperti:</span>
      {rows.map((r) => (
        <span key={r.owner.id} className="inline-flex items-center gap-1.5 text-sm">
          <OwnerChip user={r.owner} variant="compact" />
          <span className="text-fg">{r.owner.display_name}</span>
          <span className="text-fg-muted">·</span>
          <span className="font-medium">{r.count}</span>
          {r.overdue > 0 && (
            <span className="text-alert text-xs ml-0.5">
              ({r.overdue} in ritardo)
            </span>
          )}
        </span>
      ))}
    </div>
  );
}

export function WallToday() {
  const { summary, refreshSummary } = useOutletContext<OutletCtx>();
  const [picked, setPicked] = useState<WallItem | null>(null);

  if (!summary) {
    return (
      <div className="text-fg-muted text-center py-8">
        <span className="animate-breathe">Carico l'agenda di oggi…</span>
      </div>
    );
  }

  const { today, upcoming, pending_by_owner } = summary;
  const hasToday = today.items.length > 0 || today.open_no_date.length > 0;

  return (
    <div className="flex flex-col gap-6 mt-2">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
      {/* Today timeline */}
      <section className="lg:col-span-7 flex flex-col gap-2">
        <h2
          className="font-display text-fg-soft mb-1"
          style={{ fontSize: 'clamp(20px, 1.8vw, 28px)' }}
        >
          Oggi
        </h2>
        {!hasToday && (
          <div className="rounded-xl bg-surface2/40 px-6 py-10 text-center">
            <span className="text-fg-muted">
              Niente in agenda per oggi. Goditelo.
            </span>
          </div>
        )}
        {today.items.length > 0 && (
          <div className="flex flex-col gap-2">
            {today.items.map((it) => (
              <ItemRow
                key={`${it.kind}-${it.id}`}
                item={it}
                onPick={setPicked}
              />
            ))}
          </div>
        )}
        {today.open_no_date.length > 0 && (
          <div className="mt-4">
            <h3 className="text-fg-muted text-sm mb-2">
              Da fare (senza scadenza precisa)
            </h3>
            <div className="flex flex-col gap-1.5">
              {today.open_no_date.slice(0, 8).map((it) => (
                <button
                  key={`nd-${it.id}`}
                  type="button"
                  onClick={() => setPicked(it)}
                  className="w-full text-left flex items-center gap-3 px-3 py-2 rounded-md bg-surface2/30 hover:bg-surface2/50"
                >
                  <OwnerChip user={it.owner} variant="dot" />
                  <span className="flex-1 truncate" title={it.title}>
                    {it.title}
                  </span>
                  <OwnerChip user={it.owner} variant="compact" />
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Upcoming */}
      <section className="lg:col-span-5 flex flex-col gap-3">
        <h2
          className="font-display text-fg-soft mb-1"
          style={{ fontSize: 'clamp(20px, 1.8vw, 28px)' }}
        >
          Prossimi giorni
        </h2>
        {upcoming.map((d) => (
          <UpcomingCard
            key={d.date}
            date={d.date}
            count={d.count}
            preview={d.preview}
          />
        ))}
        <PendingByOwner rows={pending_by_owner} />
      </section>
      </div>

      {/* Cameras strip */}
      <WallCameraStrip />

      {picked && (
        <WallItemDetail
          item={picked}
          family={summary.family}
          onClose={() => setPicked(null)}
          onChanged={() => refreshSummary?.()}
        />
      )}
    </div>
  );
}
