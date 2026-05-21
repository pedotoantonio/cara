// Large, friendly header used at the top of section pages
// (Tasks, Shopping, Notes, News). Replaces the small `h1` so the page
// reads as "you're now in the X room of CARA". Icon + title + optional
// counter chip + optional progress ring.

import type { ReactNode } from 'react';

import { Icon, type IconName } from '../icons';
import { cn } from './cn';
import { ProgressRing } from './ProgressRing';
import type { CategoryTint } from './CategoryCard';

const TINTS: Record<CategoryTint, { bg: string; fg: string }> = {
  sage:       { bg: 'bg-emerald-100/70 dark:bg-emerald-500/15',  fg: 'text-emerald-700 dark:text-emerald-300' },
  terracotta: { bg: 'bg-orange-100/70  dark:bg-orange-500/15',   fg: 'text-orange-700  dark:text-orange-300' },
  gold:       { bg: 'bg-amber-100/70   dark:bg-amber-500/15',    fg: 'text-amber-700   dark:text-amber-300' },
  ocean:      { bg: 'bg-sky-100/70     dark:bg-sky-500/15',      fg: 'text-sky-700     dark:text-sky-300' },
  plum:       { bg: 'bg-violet-100/70  dark:bg-violet-500/15',   fg: 'text-violet-700  dark:text-violet-300' },
  coral:      { bg: 'bg-rose-100/70    dark:bg-rose-500/15',     fg: 'text-rose-700    dark:text-rose-300' },
  amber:      { bg: 'bg-yellow-100/70  dark:bg-yellow-500/15',   fg: 'text-yellow-700  dark:text-yellow-300' },
  mint:       { bg: 'bg-teal-100/70    dark:bg-teal-500/15',     fg: 'text-teal-700    dark:text-teal-300' },
  rose:       { bg: 'bg-pink-100/70    dark:bg-pink-500/15',     fg: 'text-pink-700    dark:text-pink-300' },
};

export interface CategoryHeaderProps {
  icon: IconName;
  title: string;
  subtitle?: string | null;
  tint?: CategoryTint;
  /** Optional pill counter (e.g. "5 da fare"). */
  pill?: string | null;
  /** Optional progress 0..1 — when set, shows a small ring on the right. */
  progress?: number;
  progressLabel?: string;
  progressCaption?: string;
  className?: string;
  /** Right-aligned slot for extra controls (toggles, filters). */
  right?: ReactNode;
}

export function CategoryHeader({
  icon,
  title,
  subtitle,
  tint = 'ocean',
  pill,
  progress,
  progressLabel,
  progressCaption,
  className,
  right,
}: CategoryHeaderProps) {
  const t = TINTS[tint];
  return (
    <header
      className={cn(
        'rounded-3xl p-5 md:p-6 ring-1 ring-fg/6 shadow-sm overflow-hidden relative',
        t.bg,
        className,
      )}
    >
      <div className="flex items-start gap-5">
        <div className={cn(
          'w-16 h-16 md:w-20 md:h-20 rounded-2xl flex items-center justify-center shadow-sm',
          'bg-bg/60 backdrop-blur-sm',
        )}>
          <span className={t.fg}>
            <Icon name={icon} size={40} />
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="font-display text-fg leading-tight" style={{ fontSize: 'clamp(24px, 4vw, 36px)' }}>
            {title}
          </h1>
          {subtitle && (
            <p className="text-fg-soft mt-1 leading-snug" style={{ fontSize: 'clamp(13px, 1.4vw, 15px)' }}>
              {subtitle}
            </p>
          )}
          {pill && (
            <span className={cn(
              'inline-flex items-center mt-2.5 px-3 py-1 rounded-pill text-xs font-medium',
              'bg-bg/70 backdrop-blur-sm ring-1 ring-fg/8',
              t.fg,
            )}>
              {pill}
            </span>
          )}
        </div>
        {typeof progress === 'number' && (
          <div className="shrink-0">
            <ProgressRing
              value={progress}
              size={84}
              thickness={7}
              primaryLabel={progressLabel}
              caption={progressCaption}
            />
          </div>
        )}
        {right && <div className="shrink-0">{right}</div>}
      </div>
    </header>
  );
}
