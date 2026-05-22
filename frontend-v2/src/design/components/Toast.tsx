import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/cn';
import type { AccentToken } from '../tokens';

interface ToastItem {
  id: number;
  title: string;
  body?: string;
  tone: AccentToken | 'neutral';
  ttl: number;
}

interface ToastCtxValue {
  push: (t: Omit<ToastItem, 'id' | 'ttl'> & { ttl?: number }) => void;
}

const ToastCtx = createContext<ToastCtxValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const push: ToastCtxValue['push'] = useCallback((t) => {
    const id = Date.now() + Math.random();
    const ttl = t.ttl ?? 4000;
    setItems((cur) => [...cur, { id, ttl, ...t }]);
    window.setTimeout(() => {
      setItems((cur) => cur.filter((x) => x.id !== id));
    }, ttl);
  }, []);

  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="fixed top-[calc(var(--safe-top,0)+0.5rem)] right-4 z-[70] pointer-events-none flex flex-col gap-2 w-[min(360px,calc(100vw-2rem))]">
        <AnimatePresence>
          {items.map((it) => (
            <motion.div
              key={it.id}
              initial={{ opacity: 0, x: 80 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 40, transition: { duration: 0.16 } }}
              transition={{ type: 'spring', damping: 22, stiffness: 240 }}
              className={cn(
                'pointer-events-auto rounded-md shadow-2 bg-bg-elevated px-4 py-3 border border-border-soft',
                'flex items-start gap-3',
              )}
            >
              <span
                className={cn(
                  'mt-1 inline-block h-2 w-2 rounded-full',
                  it.tone === 'neutral' && 'bg-text-secondary',
                  it.tone === 'coral' && 'bg-accent-coral',
                  it.tone === 'mint' && 'bg-accent-mint',
                  it.tone === 'sun' && 'bg-accent-sun',
                  it.tone === 'sky' && 'bg-accent-sky',
                  it.tone === 'lilac' && 'bg-accent-lilac',
                  it.tone === 'rose' && 'bg-accent-rose',
                  it.tone === 'grass' && 'bg-accent-grass',
                  it.tone === 'clay' && 'bg-accent-clay',
                )}
              />
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm text-text-primary">{it.title}</div>
                {it.body && <div className="mt-0.5 text-xs text-text-secondary">{it.body}</div>}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error('useToast deve essere usato dentro <ToastProvider>');
  return ctx;
}

// Re-export motion utilities used in this module so consumers don't need
// a separate import in the (common) case where they show a toast.
export { motion, AnimatePresence } from 'framer-motion';
