import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CaraFace } from './CaraFace';
import { useAvatarStore } from '@/state/avatar';
import { glowFor } from '@/design/tokens';
import { cn } from '@/lib/cn';

interface FloatingAvatarProps {
  onTap?: () => void;
  /** Long-press handler (700ms). Use to start voice immediately. */
  onLongPress?: () => void;
}

const SIZE_PX = 72;

/**
 * FloatingAvatar — compagna persistente in basso a destra.
 * Visibile in ogni page eccetto quella che usa l'avatar HERO (HubHome).
 *
 * - tap → onTap (apre drawer)
 * - long-press 700ms → onLongPress (start voice subito)
 * - pulse animato se pendingNotifications > 0
 * - glow colorato che cambia con `glowAccent`
 */
export function FloatingAvatar({ onTap, onLongPress }: FloatingAvatarProps) {
  const { size, energy, emotion, glowAccent, pendingNotifications, caption, posture } =
    useAvatarStore();

  const [showCaption, setShowCaption] = useState(true);
  const longPressTimer = useRef<number | null>(null);
  const longPressFired = useRef(false);

  // Auto-fade della caption dopo 4s
  useEffect(() => {
    if (!caption) return;
    setShowCaption(true);
    const t = window.setTimeout(() => setShowCaption(false), 4000);
    return () => window.clearTimeout(t);
  }, [caption]);

  if (size === 'hero') return null; // l'hero lo renderizza la HubHome direttamente

  const glow = glowFor[glowAccent];

  function startPress() {
    longPressFired.current = false;
    longPressTimer.current = window.setTimeout(() => {
      longPressFired.current = true;
      onLongPress?.();
    }, 700);
  }
  function endPress(triggerTap: boolean) {
    if (longPressTimer.current) {
      window.clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
    if (triggerTap && !longPressFired.current) {
      onTap?.();
    }
  }

  return (
    <div
      className="fixed z-30 pointer-events-none"
      style={{
        right: 'calc(env(safe-area-inset-right, 0) + 1rem)',
        bottom: 'calc(env(safe-area-inset-bottom, 0) + 5rem)', // sopra la bottom nav
      }}
    >
      <div className="flex flex-col items-end gap-2 pointer-events-auto">
        <AnimatePresence>
          {caption && showCaption && (
            <motion.div
              initial={{ opacity: 0, x: 12, scale: 0.95 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 12, scale: 0.95 }}
              transition={{ type: 'spring', damping: 24, stiffness: 280 }}
              className="rounded-md bg-bg-elevated shadow-2 border border-border-soft px-3 py-1.5 max-w-[60vw]"
            >
              <p className="text-sm text-text-primary leading-snug whitespace-nowrap overflow-hidden text-ellipsis">
                {caption}
              </p>
            </motion.div>
          )}
        </AnimatePresence>

        <motion.button
          type="button"
          aria-label="Parla con CARA"
          onMouseDown={startPress}
          onTouchStart={startPress}
          onMouseUp={() => endPress(true)}
          onMouseLeave={() => endPress(false)}
          onTouchEnd={() => endPress(true)}
          onTouchCancel={() => endPress(false)}
          className={cn(
            'relative rounded-full bg-bg-elevated p-1.5 transition-shadow duration-base ease-smooth',
            'focus-visible:ring-2 focus-visible:ring-accent-coral focus-visible:ring-offset-2',
            posture === 'peeking' && 'animate-pulse-soft',
          )}
          style={
            {
              '--avatar-glow-color': glow,
              boxShadow: `0 0 ${pendingNotifications > 0 ? 36 : 22}px 3px ${glow}, 0 4px 12px rgba(20,24,40,0.08)`,
            } as React.CSSProperties
          }
          whileTap={{ scale: 0.92 }}
          whileHover={{ scale: 1.05 }}
        >
          <CaraFace size={SIZE_PX} energy={energy} emotion={emotion} />

          {pendingNotifications > 0 && (
            <motion.span
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              className="absolute -top-1 -right-1 inline-flex items-center justify-center min-w-[20px] h-[20px] px-1 rounded-full bg-accent-coral text-text-inverse text-xs font-semibold shadow-1"
            >
              {pendingNotifications > 9 ? '9+' : pendingNotifications}
            </motion.span>
          )}
        </motion.button>
      </div>
    </div>
  );
}
