// Input + Textarea — bordo morbido, focus ring accent caldo.

import { forwardRef } from 'react';
import type {
  InputHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react';
import { cn } from './cn';
import { Icon, type IconName } from '../icons';

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  iconLeft?: IconName;
  invalid?: boolean;
  size?: 'sm' | 'md' | 'lg';
}

const inputSize = {
  sm: 'h-9 text-sm',
  md: 'h-11',
  lg: 'h-12 text-md',
} as const;

const baseField =
  'w-full bg-surface1 text-fg rounded-lg border-0 ring-1 ring-fg/8 ' +
  'placeholder:text-fg-muted ' +
  'transition-all duration-180 ease-spring ' +
  'focus:ring-2 focus:ring-accent focus:bg-bg ' +
  'disabled:opacity-50 disabled:cursor-not-allowed';

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { iconLeft, invalid, size = 'md', className, ...rest },
  ref,
) {
  if (iconLeft) {
    return (
      <div className="relative">
        <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-fg-muted">
          <Icon name={iconLeft} size={18} />
        </span>
        <input
          ref={ref}
          className={cn(
            baseField,
            inputSize[size],
            'pl-10 pr-3',
            invalid && 'ring-alert focus:ring-alert',
            className,
          )}
          {...rest}
        />
      </div>
    );
  }
  return (
    <input
      ref={ref}
      className={cn(
        baseField,
        inputSize[size],
        'px-3.5',
        invalid && 'ring-alert focus:ring-alert',
        className,
      )}
      {...rest}
    />
  );
});

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { invalid, className, rows = 3, ...rest },
  ref,
) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      className={cn(
        baseField,
        'px-3.5 py-2.5 leading-relaxed resize-none',
        invalid && 'ring-alert focus:ring-alert',
        className,
      )}
      {...rest}
    />
  );
});

interface FieldProps {
  label?: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
  className?: string;
}

export function Field({ label, hint, error, children, className }: FieldProps) {
  return (
    <label className={cn('block', className)}>
      {label && (
        <div className="text-xs font-medium uppercase tracking-wide text-fg-soft mb-1.5">
          {label}
        </div>
      )}
      {children}
      {error ? (
        <div className="text-xs text-alert mt-1.5">{error}</div>
      ) : hint ? (
        <div className="text-xs text-fg-muted mt-1.5">{hint}</div>
      ) : null}
    </label>
  );
}
