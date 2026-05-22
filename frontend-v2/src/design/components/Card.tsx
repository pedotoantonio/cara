import { type HTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  elevation?: 0 | 1 | 2 | 3;
  padding?: 'none' | 'sm' | 'base' | 'lg';
  surface?: 'base' | 'elevated' | 'surface';
}

const PADDING = {
  none: '',
  sm: 'p-3',
  base: 'p-4',
  lg: 'p-6',
};

const ELEVATION = {
  0: 'border border-border-soft',
  1: 'shadow-1 border border-border-soft',
  2: 'shadow-2',
  3: 'shadow-3',
};

const SURFACE = {
  base: 'bg-bg-base',
  elevated: 'bg-bg-elevated',
  surface: 'bg-bg-surface',
};

export function Card({
  elevation = 1,
  padding = 'base',
  surface = 'base',
  className,
  children,
  ...rest
}: CardProps) {
  return (
    <div
      className={cn(
        'rounded-lg',
        SURFACE[surface],
        ELEVATION[elevation],
        PADDING[padding],
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardTitle({ children, className }: { children: ReactNode; className?: string }) {
  return <h3 className={cn('text-lg font-semibold text-text-primary', className)}>{children}</h3>;
}

export function CardSubtitle({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn('text-sm text-text-secondary', className)}>{children}</p>;
}
