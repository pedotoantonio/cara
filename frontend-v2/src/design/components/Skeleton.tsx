import { type HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'rect' | 'text' | 'circle';
}

export function Skeleton({ variant = 'rect', className, ...rest }: SkeletonProps) {
  return (
    <div
      className={cn(
        'animate-pulse bg-bg-surface',
        variant === 'text' && 'h-4 rounded-sm',
        variant === 'rect' && 'rounded-md',
        variant === 'circle' && 'rounded-full',
        className,
      )}
      {...rest}
    />
  );
}
