import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/lib/cn';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'sm' | 'base' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
  fullWidth?: boolean;
}

const VARIANT: Record<Variant, string> = {
  primary:
    'bg-accent-coral text-text-inverse hover:bg-[#ff5252] active:bg-[#ee4848] shadow-1 hover:shadow-2 disabled:bg-border-strong disabled:text-text-muted disabled:shadow-none',
  secondary:
    'bg-bg-surface text-text-primary border border-border-soft hover:border-border-strong hover:bg-white disabled:opacity-50',
  ghost:
    'bg-transparent text-text-primary hover:bg-bg-surface active:bg-border-soft disabled:opacity-40',
  danger:
    'bg-bg-base text-accent-coral border border-accent-coral/30 hover:bg-accent-coral hover:text-text-inverse disabled:opacity-40',
};

const SIZE: Record<Size, string> = {
  sm: 'h-9 px-3 text-sm rounded-sm gap-1.5',
  base: 'h-11 px-5 text-base rounded-md gap-2',
  lg: 'h-14 px-7 text-md rounded-lg gap-2.5',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'primary',
      size = 'base',
      loading,
      leftIcon,
      rightIcon,
      fullWidth,
      disabled,
      className,
      children,
      ...rest
    },
    ref,
  ) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center font-medium transition-all duration-base ease-smooth',
        'select-none touch-manipulation outline-none',
        'focus-visible:ring-2 focus-visible:ring-accent-coral focus-visible:ring-offset-2',
        VARIANT[variant],
        SIZE[size],
        fullWidth && 'w-full',
        className,
      )}
      {...rest}
    >
      {loading ? (
        <span className="inline-block h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
      ) : (
        leftIcon
      )}
      <span>{children}</span>
      {!loading && rightIcon}
    </button>
  ),
);
Button.displayName = 'Button';
