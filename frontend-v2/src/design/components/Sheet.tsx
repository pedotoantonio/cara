import { useEffect, type ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/cn';

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  side?: 'bottom' | 'right';
  className?: string;
}

/**
 * Sheet — bottom drawer (mobile) o right drawer (desktop).
 * - Dismissible via swipe down/right o tap su backdrop
 * - Safe-area aware
 * - ESC chiude
 */
export function Sheet({ open, onClose, title, children, side = 'bottom', className }: SheetProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    document.documentElement.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.documentElement.style.overflow = '';
    };
  }, [open, onClose]);

  const bottom = side === 'bottom';

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.22 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-text-primary/30 backdrop-blur-sm"
          />
          <motion.div
            initial={bottom ? { y: '100%' } : { x: '100%' }}
            animate={bottom ? { y: 0 } : { x: 0 }}
            exit={bottom ? { y: '100%' } : { x: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 240 }}
            drag={bottom ? 'y' : 'x'}
            dragConstraints={{ top: 0, bottom: 0, left: 0, right: 0 }}
            dragElastic={{ top: 0, bottom: 0.3, left: 0, right: 0.3 }}
            onDragEnd={(_, info) => {
              const should = bottom
                ? info.offset.y > 100 || info.velocity.y > 400
                : info.offset.x > 80 || info.velocity.x > 400;
              if (should) onClose();
            }}
            className={cn(
              'fixed z-50 bg-bg-elevated shadow-3',
              bottom
                ? 'inset-x-0 bottom-0 rounded-t-2xl max-h-[90vh]'
                : 'inset-y-0 right-0 w-full sm:w-[420px] rounded-l-2xl',
              className,
            )}
            style={{ paddingBottom: bottom ? 'env(safe-area-inset-bottom)' : undefined }}
          >
            {bottom && (
              <div className="flex justify-center pt-2.5 pb-1">
                <span className="h-1 w-10 rounded-full bg-border-strong/60" />
              </div>
            )}
            {title && (
              <div className="px-5 pt-3 pb-2">
                <h2 className="text-xl font-semibold">{title}</h2>
              </div>
            )}
            <div className="overflow-y-auto p-5">{children}</div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
