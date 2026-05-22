// Wake Lock — tieni acceso lo schermo durante azioni che lo richiedono:
// - Conversazione attiva con CARA (TTS in playback)
// - Spesa in corso (vista lista in cucina)
// - Radio in play, ricetta aperta
// - Enrollment volto

import { useEffect, useRef } from 'react';

interface UseWakeLockOptions {
  /** Quando true, richiedi wake lock. Quando false, rilascia. */
  active: boolean;
  /** Etichetta per logging/debug. */
  reason?: string;
}

// Polyfill type — lib.dom.d.ts non sempre ha WakeLock pronto.
interface WakeLockSentinelLike {
  release: () => Promise<void>;
  addEventListener: (type: 'release', listener: () => void) => void;
}

interface WakeLockApi {
  request: (type: 'screen') => Promise<WakeLockSentinelLike>;
}

export function useWakeLock({ active, reason }: UseWakeLockOptions) {
  const sentinelRef = useRef<WakeLockSentinelLike | null>(null);

  useEffect(() => {
    if (!active) {
      void releaseExisting(sentinelRef);
      return;
    }
    const wl = (navigator as Navigator & { wakeLock?: WakeLockApi }).wakeLock;
    if (!wl) return; // unsupported (iOS < 16.4, Firefox)

    let cancelled = false;

    (async () => {
      try {
        const sentinel = await wl.request('screen');
        if (cancelled) {
          await sentinel.release();
          return;
        }
        sentinelRef.current = sentinel;
        sentinel.addEventListener('release', () => {
          // Visibility o OS revoked — release silenzioso
          sentinelRef.current = null;
        });
      } catch (err) {
        // Non-fatal — log only
        console.warn('[wakeLock] failed', reason, err);
      }
    })();

    // Re-request se la visibilità torna visible (browser revoca wake-lock
    // automaticamente quando l'app va in background)
    const onVisibility = () => {
      if (document.visibilityState === 'visible' && !sentinelRef.current && active) {
        wl.request('screen')
          .then((s) => {
            sentinelRef.current = s;
            s.addEventListener('release', () => {
              sentinelRef.current = null;
            });
          })
          .catch(() => undefined);
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', onVisibility);
      void releaseExisting(sentinelRef);
    };
  }, [active, reason]);
}

async function releaseExisting(ref: React.MutableRefObject<WakeLockSentinelLike | null>) {
  if (ref.current) {
    try {
      await ref.current.release();
    } catch {
      /* noop */
    }
    ref.current = null;
  }
}
