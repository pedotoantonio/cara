import { forwardRef } from 'react';
import type { ButtonHTMLAttributes } from 'react';
import { cn } from './cn';
import { Icon, type IconName } from '../icons';

type Variant = 'plain' | 'surface' | 'accent';
type Size = 'sm' | 'md' | 'lg';

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  name: IconName;
  variant?: Variant;
  size?: Size;
  label: string;
}

const sizeMap: Record<Size, { box: string; icon: number }> = {
  sm: { box: 'h-8 w-8',    icon: 18 },
  md: { box: 'h-10 w-10',  icon: 20 },
  lg: { box: 'h-12 w-12',  icon: 24 },
};

const variantMap: Record<Variant, string> = {
  plain:   'text-fg-soft hover:text-fg hover:bg-surface1',
  surface: 'bg-surface1 text-fg hover:bg-surface2 shadow-soft',
  accent:  'bg-accent text-ivory shadow-warm hover:bg-accent-dark',
};

export const IconButton = forwardRef<HTMLButtonElement, Props>(function IconButton(
  { name, variant = 'plain', size = 'md', label, className, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      className={cn(
        'inline-flex items-center justify-center rounded-pill',
        'transition-all duration-180 ease-spring',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        sizeMap[size].box,
        variantMap[variant],
        className,
      )}
      {...rest}
    >
      <Icon name={name} size={sizeMap[size].icon} />
    </button>
  );
});
