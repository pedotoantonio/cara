import { useState, type ReactNode } from 'react';
import { motion } from 'framer-motion';
import { Trash, Check } from '@phosphor-icons/react';
import { cn } from '@/lib/cn';

interface ListItemCardProps {
  done?: boolean;
  /** When defined, shows a checkbox on the left and calls back on toggle. */
  onToggleDone?: (next: boolean) => void;
  onDelete?: () => void;
  /** Optional accent for the checkbox / left side. */
  accent?: 'mint' | 'rose' | 'coral' | 'sun' | 'lilac';
  children: ReactNode;
  className?: string;
}

const ACCENT_CHECKED: Record<NonNullable<ListItemCardProps['accent']>, string> = {
  mint: 'bg-accent-mint border-accent-mint',
  rose: 'bg-accent-rose border-accent-rose',
  coral: 'bg-accent-coral border-accent-coral',
  sun: 'bg-accent-sun border-accent-sun',
  lilac: 'bg-accent-lilac border-accent-lilac',
};

export function ListItemCard({
  done,
  onToggleDone,
  onDelete,
  accent = 'mint',
  children,
  className,
}: ListItemCardProps) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: 60, transition: { duration: 0.18 } }}
      transition={{ type: 'spring', damping: 28, stiffness: 280 }}
      className={cn(
        'flex items-center gap-3 rounded-md bg-bg-base border border-border-soft px-3 py-3 shadow-1',
        done && 'bg-bg-surface',
        className,
      )}
    >
      {onToggleDone && (
        <button
          type="button"
          onClick={() => onToggleDone(!done)}
          aria-label={done ? 'Riapri' : 'Completa'}
          className={cn(
            'inline-flex items-center justify-center w-7 h-7 rounded-md border-2 transition-all flex-shrink-0',
            done ? ACCENT_CHECKED[accent] + ' text-text-inverse' : 'border-border-strong bg-bg-base',
          )}
        >
          {done && <Check size={16} weight="bold" />}
        </button>
      )}

      <div className={cn('flex-1 min-w-0', done && 'opacity-60 line-through')}>{children}</div>

      {onDelete && (
        <button
          type="button"
          onClick={() => {
            if (confirmingDelete) onDelete();
            else {
              setConfirmingDelete(true);
              window.setTimeout(() => setConfirmingDelete(false), 2200);
            }
          }}
          aria-label={confirmingDelete ? 'Confermi eliminazione' : 'Elimina'}
          className={cn(
            'inline-flex items-center justify-center w-9 h-9 rounded-md transition-colors flex-shrink-0',
            confirmingDelete
              ? 'bg-accent-coral text-text-inverse'
              : 'text-text-muted hover:text-accent-coral hover:bg-accent-coral/12',
          )}
        >
          <Trash size={18} weight={confirmingDelete ? 'fill' : 'regular'} />
        </button>
      )}
    </motion.li>
  );
}
