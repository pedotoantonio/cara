/**
 * Floating top-right indicator that shows the current AI activity (idle /
 * listening / thinking / speaking) on every page.
 *
 * Inspired by Lumo's LED ring: ambient feedback of the system state that
 * the user can glance at without context-switching. Adapted to the PWA:
 * a tiny pulsing pill in the corner.
 *
 * Hidden when phase === 'idle' to keep the UI quiet during normal use.
 */

import { useEffect, useState } from 'react';

import { getAiPhase, subscribeAiPhase, type AiPhase } from '../lib/aiState';

const META: Record<Exclude<AiPhase, 'idle'>, { label: string; icon: string; tone: string }> = {
  listening: {
    label: 'In ascolto…',
    icon: '🎙',
    tone: 'bg-rose-500/15 border-rose-400/50 text-rose-200',
  },
  thinking: {
    label: 'Sto pensando…',
    icon: '💭',
    tone: 'bg-violet-500/15 border-violet-400/50 text-violet-200',
  },
  speaking: {
    label: 'Sto parlando…',
    icon: '🔊',
    tone: 'bg-amber-500/15 border-amber-400/50 text-amber-200',
  },
};

export function AmbientStateBanner() {
  const [phase, setPhase] = useState<AiPhase>(getAiPhase());

  useEffect(() => subscribeAiPhase(setPhase), []);

  if (phase === 'idle') return null;

  const m = META[phase];
  return (
    <div
      role="status"
      aria-live="polite"
      className={`fixed z-[55] top-3 left-1/2 -translate-x-1/2
                  md:left-auto md:right-4 md:translate-x-0
                  rounded-full border px-3 py-1 text-[11px]
                  flex items-center gap-1.5 backdrop-blur
                  shadow-md ${m.tone}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
      <span className="text-base leading-none">{m.icon}</span>
      <span className="font-medium tracking-wide">{m.label}</span>
    </div>
  );
}
