// Single day cell in the monthly grid. Shows day number + up to N
// chips with owner color + overflow link.

import type { WallDay, WallItem } from '../../api/wall';
import { OwnerChip } from './OwnerChip';

const MAX_CHIPS = 4;

function fmtTimeShort(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  if (d.getHours() === 0 && d.getMinutes() === 0) return '';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

export function WallDayCell({
  day,
  monthVisible,
  onShowMore,
  onPickItem,
}: {
  day: WallDay;
  monthVisible: boolean;
  onShowMore?: (day: WallDay) => void;
  onPickItem?: (item: WallItem) => void;
}) {
  const dayNum = parseInt(day.date.slice(-2), 10);
  const dim = !monthVisible || (day.in_month === false);
  const overflow = Math.max(0, day.items.length - MAX_CHIPS);

  return (
    <div
      className={[
        // Phones: compact cell, 56 px min-h is enough to show the day
        // number + 1-2 chips. Tablets+: 120 px wall-poster size.
        'flex flex-col gap-0.5 sm:gap-1 p-1 sm:p-2 rounded-md min-h-[56px] sm:min-h-[120px]',
        'border border-surface2/60',
        dim ? 'opacity-40 bg-transparent' : 'bg-bg/30',
        day.is_holiday && !dim ? 'bg-rose-50/40 dark:bg-rose-900/20' : '',
        day.is_pre_holiday && !day.is_holiday && !dim
          ? 'bg-amber-50/30 dark:bg-amber-900/10' : '',
      ].join(' ')}
    >
      <div className="flex items-center justify-between gap-1">
        <span
          className={[
            'inline-flex items-center justify-center font-display',
            day.is_today
              // Today badge — 24 px circle on mobile, 32 px on desktop.
              ? 'rounded-full bg-accent text-bg w-6 h-6 sm:w-8 sm:h-8 font-medium text-xs sm:text-base'
              : day.is_holiday
                ? 'text-rose-600 dark:text-rose-300 font-semibold text-sm sm:text-base'
                : day.is_pre_holiday
                  ? 'text-amber-600 dark:text-amber-300 font-medium text-sm sm:text-base'
                  : day.is_weekend
                    ? 'text-fg-soft text-sm sm:text-base'
                    : 'text-fg text-sm sm:text-base',
          ].join(' ')}
        >
          {dayNum}
        </span>
        <div className="flex items-center gap-1">
          {day.moon_marker && !dim && (
            <span
              className="text-sm sm:text-base leading-none"
              title={`Luna · ${day.moon_marker}`}
              aria-label="Fase lunare"
            >
              {day.moon_marker}
            </span>
          )}
          {day.birthdays && day.birthdays.length > 0 && (
            <span
              className="text-base leading-none"
              title={day.birthdays.map((b) => `🎂 ${b.name}`).join(', ')}
            >
              🎂
            </span>
          )}
        </div>
      </div>
      {day.saint && !dim && (
        <div
          className="text-[10px] leading-tight text-fg-muted truncate first-letter:capitalize"
          title={day.saint}
        >
          {day.saint}
        </div>
      )}
      {day.birthdays && day.birthdays.length > 0 && !dim && (
        <div className="flex flex-col gap-0.5">
          {day.birthdays.map((b) => (
            <span
              key={b.user_id}
              className="text-[11px] leading-tight rounded px-1.5 py-0.5 truncate"
              style={{
                background: `${b.color}30`,
                borderLeft: `3px solid ${b.color}`,
              }}
              title={`Compleanno di ${b.name} (${b.born_year})`}
            >
              🎂 {b.name}
            </span>
          ))}
        </div>
      )}
      <div className="flex flex-col gap-0.5 overflow-hidden">
        {day.items.slice(0, MAX_CHIPS).map((it) => {
          const time = fmtTimeShort(it.start ?? it.due_date);
          const Tag: keyof JSX.IntrinsicElements = onPickItem ? 'button' : 'div';
          return (
            <Tag
              key={`${it.kind}-${it.id}`}
              {...(onPickItem
                ? {
                    type: 'button',
                    onClick: (e: React.MouseEvent) => {
                      e.stopPropagation();
                      onPickItem(it);
                    },
                  }
                : {})}
              className="flex items-center gap-1 text-xs leading-tight rounded px-1.5 py-0.5 w-full text-left hover:brightness-110"
              style={{
                background: `${it.owner?.color ?? '#94a3b8'}22`,
                borderLeft: `3px solid ${it.owner?.color ?? '#94a3b8'}`,
              }}
              title={`${it.title}${it.owner ? ` · ${it.owner.display_name}` : ''}`}
            >
              {time && (
                <span className="font-mono text-fg-muted text-2xs">{time}</span>
              )}
              <span
                className={[
                  'flex-1 truncate',
                  it.kind === 'task' && it.done ? 'line-through opacity-60' : '',
                ].join(' ')}
              >
                {truncate(it.title, 22)}
              </span>
            </Tag>
          );
        })}
        {overflow > 0 && onShowMore && (
          <button
            type="button"
            onClick={() => onShowMore(day)}
            className="text-2xs text-fg-muted hover:text-fg text-left mt-0.5"
          >
            + {overflow} altr{overflow === 1 ? 'o' : 'i'}
          </button>
        )}
      </div>
    </div>
  );
}

export function WallDayDetailModal({
  day,
  onClose,
  onPickItem,
}: {
  day: WallDay;
  onClose: () => void;
  onPickItem?: (item: WallItem) => void;
}) {
  return (
    <div
      className="fixed inset-0 z-30 bg-black/50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-bg rounded-xl max-w-lg w-full max-h-[80vh] overflow-y-auto p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3
          className="font-display text-fg mb-4"
          style={{ fontSize: 'clamp(20px, 2vw, 28px)' }}
        >
          {new Date(day.date).toLocaleDateString('it-IT', {
            weekday: 'long',
            day: 'numeric',
            month: 'long',
            year: 'numeric',
          })}
        </h3>
        <div className="flex flex-col gap-2">
          {day.items.map((it) => {
            const time = fmtTimeShort(it.start ?? it.due_date);
            const Tag: keyof JSX.IntrinsicElements = onPickItem ? 'button' : 'div';
            return (
              <Tag
                key={`${it.kind}-${it.id}`}
                {...(onPickItem
                  ? {
                      type: 'button',
                      onClick: () => {
                        onPickItem(it);
                        onClose();
                      },
                    }
                  : {})}
                className="flex items-center gap-3 p-3 rounded-md bg-surface2/40 w-full text-left hover:bg-surface2/60"
                style={{ borderLeft: `4px solid ${it.owner?.color ?? '#94a3b8'}` }}
              >
                {time ? (
                  <span className="font-mono text-fg-soft text-sm w-12 flex-shrink-0">
                    {time}
                  </span>
                ) : (
                  <span className="text-fg-muted text-xs w-12 flex-shrink-0">
                    {it.kind}
                  </span>
                )}
                <span
                  className={[
                    'flex-1 min-w-0',
                    it.kind === 'task' && it.done ? 'line-through opacity-60' : '',
                  ].join(' ')}
                >
                  {it.title}
                </span>
                <OwnerChip user={it.owner} variant="compact" />
              </Tag>
            );
          })}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="mt-4 w-full rounded-pill bg-surface2 text-fg-soft py-2 hover:bg-surface2/80"
        >
          Chiudi
        </button>
      </div>
    </div>
  );
}
