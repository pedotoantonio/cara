// Bottom sheet — drawer mobile-first, full-screen su mobile,
// dialog centered su desktop. Niente librerie esterne.

import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { cn } from './cn';
import { Icon } from '../icons';

interface Props {
  open: boolean;
  onClose: () => void;
  title?: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: 'sm' | 'md' | 'lg';
}

const widthMap = {
  sm: 'sm:max-w-sm',
  md: 'sm:max-w-lg',
  lg: 'sm:max-w-2xl',
};

export function BottomSheet({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  size = 'md',
}: Props) {
  // Esc to close, lock body scroll while open.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-end justify-center sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className="absolute inset-0 bg-fg/40 backdrop-blur-sm animate-rise"
        onClick={onClose}
      />
      <div
        className={cn(
          'relative w-full bg-bg shadow-deep',
          'rounded-t-2xl sm:rounded-2xl',
          widthMap[size],
          'max-h-[90vh] flex flex-col animate-rise',
        )}
        style={{ animationDuration: '320ms' }}
      >
        {/* Pull handle (mobile only). */}
        <div className="sm:hidden flex justify-center pt-2.5 pb-1">
          <div className="h-1 w-10 rounded-full bg-fg/20" />
        </div>

        {(title || subtitle) && (
          <header className="px-6 pt-4 pb-3 flex items-start gap-3">
            <div className="flex-1 min-w-0">
              {title && (
                <h2 className="font-display text-xl text-fg leading-tight">
                  {title}
                </h2>
              )}
              {subtitle && (
                <p className="text-sm text-fg-soft mt-1">{subtitle}</p>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="text-fg-soft hover:text-fg p-1 -mr-1 rounded-pill hover:bg-surface1 transition-colors"
              aria-label="Chiudi"
            >
              <Icon name="close" size={22} />
            </button>
          </header>
        )}

        <div className="flex-1 overflow-y-auto px-6 py-3">
          {children}
        </div>

        {footer && (
          <footer className="px-6 py-4 border-t border-fg/8">
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}
