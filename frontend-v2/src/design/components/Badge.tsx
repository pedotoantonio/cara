import { type HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';
import type { AccentToken } from '../tokens';

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: AccentToken | 'neutral';
  size?: 'sm' | 'base';
  variant?: 'solid' | 'soft';
}

const TONE_SOFT: Record<AccentToken | 'neutral', string> = {
  neutral: 'bg-bg-surface text-text-secondary',
  coral: 'bg-accent-coral/12 text-accent-coral',
  mint: 'bg-accent-mint/12 text-accent-mint',
  sun: 'bg-accent-sun/20 text-[#8E6800]',
  sky: 'bg-accent-sky/12 text-accent-sky',
  lilac: 'bg-accent-lilac/12 text-accent-lilac',
  rose: 'bg-accent-rose/24 text-[#A53A5E]',
  grass: 'bg-accent-grass/12 text-accent-grass',
  clay: 'bg-accent-clay/12 text-accent-clay',
};

const TONE_SOLID: Record<AccentToken | 'neutral', string> = {
  neutral: 'bg-text-secondary text-text-inverse',
  coral: 'bg-accent-coral text-text-inverse',
  mint: 'bg-accent-mint text-text-inverse',
  sun: 'bg-accent-sun text-[#3D2C00]',
  sky: 'bg-accent-sky text-text-inverse',
  lilac: 'bg-accent-lilac text-text-inverse',
  rose: 'bg-accent-rose text-[#A53A5E]',
  grass: 'bg-accent-grass text-text-inverse',
  clay: 'bg-accent-clay text-text-inverse',
};

export function Badge({
  tone = 'neutral',
  size = 'base',
  variant = 'soft',
  className,
  children,
  ...rest
}: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center font-medium rounded-pill whitespace-nowrap',
        size === 'sm' ? 'text-xs px-2 py-0.5' : 'text-sm px-2.5 py-1',
        variant === 'solid' ? TONE_SOLID[tone] : TONE_SOFT[tone],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
