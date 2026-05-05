// Toast — provider + hook. Tono caldo, mai aggressivo.

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { cn } from './cn';
import { Icon, type IconName } from '../icons';

type ToastKind = 'info' | 'ok' | 'alert' | 'celebrate';
interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  body?: string;
  icon?: IconName;
  ttl: number;
}

interface ToastCtx {
  push: (t: Omit<ToastItem, 'id' | 'ttl'> & { ttl?: number }) => void;
}

const Ctx = createContext<ToastCtx | null>(null);

const kindStyle: Record<ToastKind, string> = {
  info:      'bg-surface1 ring-1 ring-fg/8',
  ok:        'bg-ok/12 ring-1 ring-ok/30 text-fg',
  alert:     'bg-alert/12 ring-1 ring-alert/30 text-fg',
  celebrate: 'bg-celebrate/15 ring-1 ring-celebrate/35 text-fg',
};

const kindIcon: Record<ToastKind, IconName> = {
  info:      'spark',
  ok:        'check',
  alert:     'bell',
  celebrate: 'sparkle',
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const idRef = useRef(0);

  const push = useCallback<ToastCtx['push']>(
    ({ ttl = 4000, ...rest }) => {
      const id = ++idRef.current;
      const item: ToastItem = { id, ttl, ...rest };
      setItems(prev => [...prev, item]);
      window.setTimeout(() => {
        setItems(prev => prev.filter(x => x.id !== id));
      }, ttl);
    },
    [],
  );

  const value = useMemo(() => ({ push }), [push]);

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 top-3 z-[70] flex flex-col items-center gap-2 px-3 sm:top-6">
        {items.map(t => (
          <div
            key={t.id}
            role="status"
            className={cn(
              'pointer-events-auto w-full max-w-sm rounded-xl shadow-warm px-4 py-3',
              'animate-cara-toast-in flex items-start gap-3',
              kindStyle[t.kind],
            )}
          >
            <span
              className={cn(
                'mt-0.5 shrink-0',
                t.kind === 'ok' && 'text-ok',
                t.kind === 'alert' && 'text-alert',
                t.kind === 'celebrate' && 'text-celebrate',
                t.kind === 'info' && 'text-accent',
              )}
            >
              <Icon name={t.icon ?? kindIcon[t.kind]} size={20} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="font-medium text-fg text-sm leading-snug">
                {t.title}
              </div>
              {t.body && (
                <div className="text-xs text-fg-soft mt-0.5 leading-relaxed">
                  {t.body}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): ToastCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useToast outside ToastProvider');
  return v;
}
