import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  error?: string;
  leftIcon?: ReactNode;
  rightSlot?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, hint, error, leftIcon, rightSlot, className, id, ...rest }, ref) => {
    const inputId = id ?? `input-${Math.random().toString(36).slice(2, 9)}`;
    return (
      <div className="w-full">
        {label && (
          <label htmlFor={inputId} className="mb-1.5 block text-sm font-medium text-text-secondary">
            {label}
          </label>
        )}
        <div
          className={cn(
            'flex items-center gap-2 rounded-md border bg-bg-base transition-colors duration-quick ease-smooth',
            'focus-within:border-accent-coral focus-within:ring-2 focus-within:ring-accent-coral/20',
            error ? 'border-accent-coral' : 'border-border-soft hover:border-border-strong',
          )}
        >
          {leftIcon && (
            <span className="pl-3 text-text-muted flex items-center pointer-events-none">
              {leftIcon}
            </span>
          )}
          <input
            ref={ref}
            id={inputId}
            className={cn(
              'flex-1 bg-transparent text-base text-text-primary placeholder:text-text-muted',
              'py-3 outline-none border-0 ring-0',
              leftIcon ? 'pl-2' : 'pl-3.5',
              rightSlot ? 'pr-2' : 'pr-3.5',
              className,
            )}
            {...rest}
          />
          {rightSlot && <span className="pr-2 flex items-center">{rightSlot}</span>}
        </div>
        {(hint || error) && (
          <p className={cn('mt-1 text-xs', error ? 'text-accent-coral' : 'text-text-muted')}>
            {error ?? hint}
          </p>
        )}
      </div>
    );
  },
);
Input.displayName = 'Input';
