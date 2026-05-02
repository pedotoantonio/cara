/**
 * CARA reaction toaster.
 *
 * A small overlay in the top-right that briefly shows CARA's face reacting
 * to a UI event (e.g. task ticked, shopping item bought). Implemented as a
 * global event bus + React provider so any component can fire a reaction
 * without prop-drilling.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { CaraFaceFX } from '../components/CaraFaceFX';
import { type Emotion, type EnergyState } from '../components/CaraFace';
import { playSound, type SoundName } from './sounds';

export type ReactionKind =
  | 'task_done'
  | 'shopping_added'
  | 'shopping_bought'
  | 'note_saved'
  | 'birthday'
  | 'error'
  | 'celebrate'
  | 'wake';

interface ReactionPreset {
  energy: EnergyState;
  emotion: Emotion;
  message: string;
  durationMs: number;
  sound?: SoundName;
}

const PRESETS: Record<ReactionKind, ReactionPreset> = {
  task_done:       { energy: 'idle', emotion: 'happy',  message: 'Bravo! Completata.', durationMs: 1800, sound: 'confirm' },
  shopping_added:  { energy: 'idle', emotion: 'happy',  message: 'Aggiunto alla spesa.', durationMs: 1500, sound: 'notify' },
  shopping_bought: { energy: 'idle', emotion: 'happy',  message: 'Preso!',               durationMs: 1500, sound: 'confirm' },
  note_saved:      { energy: 'idle', emotion: 'happy',  message: 'Nota salvata.',        durationMs: 1200, sound: 'notify' },
  birthday:        { energy: 'speaking', emotion: 'joyful', message: 'Tanti auguri! 🎉', durationMs: 4000, sound: 'celebrate' },
  error:           { energy: 'idle', emotion: 'error',  message: 'Qualcosa è andato storto.', durationMs: 2200, sound: 'error' },
  celebrate:       { energy: 'idle', emotion: 'joyful', message: 'Evvai!',               durationMs: 2000, sound: 'celebrate' },
  wake:            { energy: 'waking_up', emotion: 'neutral', message: 'Eccomi.',         durationMs: 1500, sound: 'wake' },
};

interface ReactionState {
  preset: ReactionPreset;
  message?: string;
  id: number;
}

interface ReactionsApi {
  trigger: (kind: ReactionKind, override?: { message?: string }) => void;
}

const ReactionsCtx = createContext<ReactionsApi | null>(null);

export function ReactionsProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<ReactionState | null>(null);
  const idRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const trigger = useCallback((kind: ReactionKind, override?: { message?: string }) => {
    const preset = PRESETS[kind];
    if (!preset) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    idRef.current += 1;
    const id = idRef.current;
    setActive({ preset, message: override?.message, id });
    if (preset.sound) playSound(preset.sound);
    timerRef.current = setTimeout(() => {
      // Only clear if this is still the most recent toast.
      setActive((cur) => (cur && cur.id === id ? null : cur));
      timerRef.current = null;
    }, preset.durationMs);
  }, []);

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  return (
    <ReactionsCtx.Provider value={{ trigger }}>
      {children}
      <ReactionToast active={active} />
    </ReactionsCtx.Provider>
  );
}

export function useReactions(): ReactionsApi {
  const ctx = useContext(ReactionsCtx);
  if (!ctx) {
    // Reactions are decorative — fail soft if provider is missing.
    return { trigger: () => undefined };
  }
  return ctx;
}

function ReactionToast({ active }: { active: ReactionState | null }) {
  if (!active) return null;
  const { preset, message } = active;
  return (
    <div
      className="pointer-events-none fixed top-4 right-4 z-50 flex items-center gap-3
                 rounded-2xl bg-slate-800/80 backdrop-blur border border-slate-700/60 px-3 py-2
                 shadow-lg animate-cara-toast-in"
      role="status"
      aria-live="polite"
    >
      <CaraFaceFX
        energy={preset.energy}
        emotion={preset.emotion}
        size={52}
        particles
        glow
      />
      <span className="text-sm text-slate-100 max-w-[40vw] truncate">
        {message ?? preset.message}
      </span>
    </div>
  );
}
