// Card — angoli morbidi, ombra calda, sembra ceramica appoggiata.
// padded=false per chi vuole gestire lo spazio internamente (es. immagine edge-to-edge).

import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from './cn';

interface Props extends HTMLAttributes<HTMLDivElement> {
  variant?: 'flat' | 'raised' | 'outline' | 'tinted';
  tint?: 'accent' | 'ok' | 'celebrate' | 'alert';
  padded?: boolean;
  hoverable?: boolean;
  children?: ReactNode;
}

const variantMap = {
  flat:    'bg-surface1',
  raised:  'bg-surface1 shadow-soft',
  outline: 'bg-bg ring-1 ring-fg/8',
  tinted:  'bg-surface2',
} as const;

const tintMap = {
  accent:    'ring-1 ring-accent/30 bg-accent/8',
  ok:        'ring-1 ring-ok/30 bg-ok/8',
  celebrate: 'ring-1 ring-celebrate/30 bg-celebrate/10',
  alert:     'ring-1 ring-alert/30 bg-alert/8',
} as const;

export function Card({
  variant = 'flat',
  tint,
  padded = true,
  hoverable,
  className,
  children,
  ...rest
}: Props) {
  return (
    <div
      className={cn(
        'rounded-xl text-fg',
        variantMap[variant],
        tint && tintMap[tint],
        padded && 'p-5',
        hoverable && 'transition-all duration-180 ease-spring hover:shadow-warm hover:-translate-y-px cursor-pointer',
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardTitle({ children, className, ...rest }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3 className={cn('font-display text-lg text-fg leading-tight', className)} {...rest}>
      {children}
    </h3>
  );
}

export function CardSubtitle({ children, className, ...rest }: HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p className={cn('text-sm text-fg-soft mt-1', className)} {...rest}>
      {children}
    </p>
  );
}
