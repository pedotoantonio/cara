// Badge — piccola etichetta, capsula. Per status, conteggi, tag.

import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from './cn';

type Tone = 'neutral' | 'accent' | 'ok' | 'alert' | 'celebrate' | 'muted';

interface Props extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  size?: 'sm' | 'md';
  dot?: boolean;
  children?: ReactNode;
}

const toneMap: Record<Tone, string> = {
  neutral:   'bg-surface2 text-fg',
  accent:    'bg-accent/15 text-accent-dark',
  ok:        'bg-ok/15 text-ok',
  alert:     'bg-alert/15 text-alert',
  celebrate: 'bg-celebrate/15 text-fg',
  muted:     'bg-surface1 text-fg-muted',
};

const sizeMap = {
  sm: 'h-5 px-2 text-2xs',
  md: 'h-6 px-2.5 text-xs',
};

export function Badge({
  tone = 'neutral',
  size = 'md',
  dot,
  className,
  children,
  ...rest
}: Props) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-pill font-medium',
        sizeMap[size],
        toneMap[tone],
        className,
      )}
      {...rest}
    >
      {dot && (
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full',
            tone === 'accent' && 'bg-accent',
            tone === 'ok' && 'bg-ok',
            tone === 'alert' && 'bg-alert',
            tone === 'celebrate' && 'bg-celebrate',
            tone === 'neutral' && 'bg-fg/40',
            tone === 'muted' && 'bg-fg-muted',
          )}
        />
      )}
      {children}
    </span>
  );
}
