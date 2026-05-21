// Big, tactile category card for the family-friendly home grid.
// Wraps a NavLink so the whole card is the tap target — large enough for
// kids and elders, soft enough to feel inviting on a tablet on the wall.
//
// Design knobs:
//   - `tint` — color family. Picks a saturated foreground + tinted
//     surface so the day theme reads as "playful" and the night theme as
//     "calm glow" without authoring two icon sets.
//   - `icon` — any name from the CARA icon set; rendered ~56px.
//   - `subtitle` — small caption under the title (e.g. "5 da fare").

import { NavLink } from 'react-router-dom';

import { Icon, type IconName } from '../icons';
import { cn } from './cn';

export type CategoryTint =
  | 'sage' | 'terracotta' | 'gold' | 'ocean' | 'plum' | 'coral'
  | 'amber' | 'mint' | 'rose';

/** Soft tint — pale background, dark accent text (per pagine interne). */
const TINTS: Record<CategoryTint, { surface: string; accent: string; ring: string }> = {
  sage:       { surface: 'bg-emerald-100/80  dark:bg-emerald-500/15',  accent: 'text-emerald-700  dark:text-emerald-300',  ring: 'ring-emerald-300/40' },
  terracotta: { surface: 'bg-orange-100/80   dark:bg-orange-500/15',   accent: 'text-orange-700   dark:text-orange-300',   ring: 'ring-orange-300/40' },
  gold:       { surface: 'bg-amber-100/80    dark:bg-amber-500/15',    accent: 'text-amber-700    dark:text-amber-300',    ring: 'ring-amber-300/40' },
  ocean:      { surface: 'bg-sky-100/80      dark:bg-sky-500/15',      accent: 'text-sky-700      dark:text-sky-300',      ring: 'ring-sky-300/40' },
  plum:       { surface: 'bg-violet-100/80   dark:bg-violet-500/15',   accent: 'text-violet-700   dark:text-violet-300',   ring: 'ring-violet-300/40' },
  coral:      { surface: 'bg-rose-100/80     dark:bg-rose-500/15',     accent: 'text-rose-700     dark:text-rose-300',     ring: 'ring-rose-300/40' },
  amber:      { surface: 'bg-yellow-100/80   dark:bg-yellow-500/15',   accent: 'text-yellow-700   dark:text-yellow-300',   ring: 'ring-yellow-300/40' },
  mint:       { surface: 'bg-teal-100/80     dark:bg-teal-500/15',     accent: 'text-teal-700     dark:text-teal-300',     ring: 'ring-teal-300/40' },
  rose:       { surface: 'bg-pink-100/80     dark:bg-pink-500/15',     accent: 'text-pink-700     dark:text-pink-300',     ring: 'ring-pink-300/40' },
};

/** Solid variant — saturated background + white text (per home grid). */
const SOLIDS: Record<CategoryTint, { bg: string; shadow: string; gradient: string }> = {
  sage:       { bg: 'bg-emerald-500',  shadow: 'shadow-emerald-300/40', gradient: 'from-emerald-400  to-emerald-600' },
  terracotta: { bg: 'bg-orange-500',   shadow: 'shadow-orange-300/40',  gradient: 'from-orange-400   to-orange-600' },
  gold:       { bg: 'bg-amber-500',    shadow: 'shadow-amber-300/40',   gradient: 'from-amber-400    to-amber-600' },
  ocean:      { bg: 'bg-sky-500',      shadow: 'shadow-sky-300/40',     gradient: 'from-sky-400      to-sky-600' },
  plum:       { bg: 'bg-violet-500',   shadow: 'shadow-violet-300/40',  gradient: 'from-violet-400   to-violet-600' },
  coral:      { bg: 'bg-rose-500',     shadow: 'shadow-rose-300/40',    gradient: 'from-rose-400     to-rose-600' },
  amber:      { bg: 'bg-yellow-500',   shadow: 'shadow-yellow-300/40',  gradient: 'from-yellow-400   to-yellow-600' },
  mint:       { bg: 'bg-teal-500',     shadow: 'shadow-teal-300/40',    gradient: 'from-teal-400     to-teal-600' },
  rose:       { bg: 'bg-pink-500',     shadow: 'shadow-pink-300/40',    gradient: 'from-pink-400     to-pink-600' },
};

export interface CategoryCardProps {
  to: string;
  icon: IconName;
  title: string;
  subtitle?: string | null;
  tint?: CategoryTint;
  /** Visual variant. `tint` = soft pastel surface, `solid` = saturated bg
   *  with white foreground (best for the home grid where the card itself
   *  is the room's color, not just its accent). */
  variant?: 'tint' | 'solid';
  /** Optional badge in the top-right corner (e.g. count of new items). */
  badge?: number | string;
  /** Override `NavLink` behavior — call an arbitrary handler instead. */
  onClick?: () => void;
  className?: string;
}

export function CategoryCard({
  to,
  icon,
  title,
  subtitle,
  tint = 'ocean',
  variant = 'tint',
  badge,
  onClick,
  className,
}: CategoryCardProps) {
  const isSolid = variant === 'solid';
  const t = TINTS[tint];
  const s = SOLIDS[tint];

  const inner = isSolid ? (
    <>
      {/* Big decorative bubble behind the icon. Pure CSS, no asset. */}
      <span
        aria-hidden="true"
        className="absolute -top-8 -right-8 w-32 h-32 rounded-full bg-white/20"
      />
      <span
        aria-hidden="true"
        className="absolute -bottom-10 -left-6 w-24 h-24 rounded-full bg-white/10"
      />
      <div className="relative flex flex-col h-full gap-3 text-white">
        <div className="w-14 h-14 rounded-2xl bg-white/25 backdrop-blur-sm flex items-center justify-center">
          <Icon name={icon} size={32} />
        </div>
        <div className="flex-1 flex flex-col justify-end gap-0.5">
          <div className="font-display text-xl leading-tight drop-shadow-sm">{title}</div>
          {subtitle ? (
            <div className="text-xs text-white/85 leading-tight">{subtitle}</div>
          ) : null}
        </div>
      </div>
      {badge !== undefined ? (
        <span className="absolute top-3 right-3 min-w-7 h-7 px-2 rounded-full inline-flex items-center justify-center text-xs font-bold bg-white text-fg shadow">
          {badge}
        </span>
      ) : null}
    </>
  ) : (
    <>
      <span
        aria-hidden="true"
        className={cn('absolute -top-6 -right-6 w-24 h-24 rounded-full opacity-50', t.surface)}
      />
      <div className="relative flex flex-col h-full gap-3">
        <div className={cn('w-14 h-14 rounded-2xl flex items-center justify-center shadow-sm', t.surface)}>
          <span className={t.accent}>
            <Icon name={icon} size={32} />
          </span>
        </div>
        <div className="flex-1 flex flex-col justify-end gap-0.5">
          <div className="font-display text-lg text-fg leading-tight">{title}</div>
          {subtitle ? (
            <div className="text-xs text-fg-muted leading-tight">{subtitle}</div>
          ) : null}
        </div>
      </div>
      {badge !== undefined ? (
        <span className={cn(
          'absolute top-3 right-3 min-w-6 h-6 px-1.5 rounded-full inline-flex items-center justify-center',
          'text-xs font-semibold bg-bg/80 backdrop-blur-sm ring-1', t.ring, t.accent,
        )}>
          {badge}
        </span>
      ) : null}
    </>
  );

  const baseClass = cn(
    'relative overflow-hidden block rounded-3xl p-5 min-h-[160px]',
    'transition-all duration-200 will-change-transform',
    'hover:-translate-y-1 active:scale-[0.97]',
    isSolid
      ? cn('bg-gradient-to-br', s.gradient, 'shadow-lg', s.shadow, 'hover:shadow-2xl')
      : 'bg-surface1 ring-1 ring-fg/6 shadow-sm hover:shadow-lg',
    className,
  );

  if (onClick && !to) {
    return (
      <button type="button" onClick={onClick} className={baseClass}>{inner}</button>
    );
  }
  return (
    <NavLink to={to} className={baseClass} onClick={onClick}>{inner}</NavLink>
  );
}
