// Button — pill, weight-driven, mai gridge.
//   variant=primary  → riempito terracotta (giorno) / amber (sera)
//   variant=ghost    → trasparente, hover surface1
//   variant=quiet    → solo testo, no bg
//   variant=alert    → mattone
//   variant=ok       → verde salvia
//   tone=display     → font-display (per CTA "moments")

import { forwardRef } from 'react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from './cn';
import { Icon, type IconName } from '../icons';

type Variant = 'primary' | 'ghost' | 'quiet' | 'alert' | 'ok' | 'surface';
type Size    = 'sm' | 'md' | 'lg' | 'xl';

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  fullWidth?: boolean;
  tone?: 'body' | 'display';
  iconLeft?: IconName;
  iconRight?: IconName;
  loading?: boolean;
  children?: ReactNode;
}

const sizeMap: Record<Size, string> = {
  sm: 'h-8 px-3 text-sm gap-1.5',
  md: 'h-10 px-4 text-sm gap-2',
  lg: 'h-12 px-5 text-base gap-2',
  xl: 'h-14 px-7 text-md gap-2.5',
};

const iconSize: Record<Size, number> = { sm: 16, md: 18, lg: 20, xl: 22 };

const variantMap: Record<Variant, string> = {
  primary:
    'bg-accent text-ivory shadow-warm hover:bg-accent-dark active:translate-y-px ' +
    '[data-theme=night]_&:text-night',
  ghost:
    'bg-transparent text-fg hover:bg-surface1 active:bg-surface2',
  quiet:
    'bg-transparent text-fg-soft hover:text-fg',
  alert:
    'bg-alert text-ivory shadow-warm hover:opacity-90',
  ok:
    'bg-ok text-ivory shadow-warm hover:opacity-90',
  surface:
    'bg-surface1 text-fg shadow-soft hover:bg-surface2',
};

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  {
    variant = 'primary',
    size = 'md',
    fullWidth,
    tone = 'body',
    iconLeft,
    iconRight,
    loading,
    className,
    disabled,
    children,
    ...rest
  },
  ref,
) {
  const isIconOnly = !children && (iconLeft || iconRight);
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center rounded-pill',
        'font-medium tracking-tight select-none',
        'transition-all duration-180 ease-spring',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
        'disabled:opacity-50 disabled:cursor-not-allowed disabled:active:translate-y-0',
        tone === 'display' && 'font-display tracking-normal',
        sizeMap[size],
        variantMap[variant],
        fullWidth && 'w-full',
        isIconOnly && 'aspect-square px-0',
        className,
      )}
      {...rest}
    >
      {loading ? (
        <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
      ) : (
        iconLeft && <Icon name={iconLeft} size={iconSize[size]} />
      )}
      {children}
      {!loading && iconRight && <Icon name={iconRight} size={iconSize[size]} />}
    </button>
  );
});
