/**
 * Big circular microphone button for the voice-first home page.
 *
 * Visual states:
 *   - idle:        emerald, gentle pulse
 *   - listening:   rose, fast animated rings
 *   - thinking:    violet, dotted spinner
 *   - speaking:    amber, soft glow (matches CARA's `speaking` energy)
 *   - disabled:    slate, no animation
 */

import { type ReactNode } from 'react';

export type MicState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'disabled';

interface MicButtonProps {
  state: MicState;
  onClick: () => void;
  size?: number;
  label?: string;
}

const TONE: Record<MicState, { ring: string; bg: string; ico: string; label: string }> = {
  idle:      { ring: 'ring-emerald-500/40', bg: 'bg-emerald-500/15 hover:bg-emerald-500/25', ico: 'text-emerald-300', label: 'Tocca per parlare' },
  listening: { ring: 'ring-rose-500/60',    bg: 'bg-rose-500/30',    ico: 'text-rose-200', label: 'Sto ascoltando…' },
  thinking:  { ring: 'ring-violet-500/60',  bg: 'bg-violet-500/20',  ico: 'text-violet-200', label: 'Sto pensando…' },
  speaking:  { ring: 'ring-amber-500/60',   bg: 'bg-amber-500/20',   ico: 'text-amber-200', label: 'Sto parlando…' },
  disabled:  { ring: 'ring-slate-700',      bg: 'bg-slate-800',      ico: 'text-slate-500', label: 'Non disponibile' },
};

export function MicButton({ state, onClick, size = 96, label }: MicButtonProps) {
  const tone = TONE[state];
  const ariaLabel = label ?? tone.label;
  return (
    <div className="flex flex-col items-center gap-2">
      <button
        type="button"
        onClick={onClick}
        disabled={state === 'disabled'}
        aria-label={ariaLabel}
        className={`relative rounded-full ring-2 ${tone.ring} ${tone.bg} flex items-center justify-center transition-all duration-200 active:scale-95`}
        style={{ width: size, height: size }}
      >
        {/* Animated rings on listening */}
        {state === 'listening' && (
          <>
            <span className="absolute inset-0 rounded-full bg-rose-500/30 animate-mic-ping" />
            <span
              className="absolute inset-0 rounded-full bg-rose-500/20 animate-mic-ping"
              style={{ animationDelay: '420ms' }}
            />
          </>
        )}
        <MicIcon className={`${tone.ico} relative`} size={size * 0.45} />
      </button>
      <p className="text-xs text-slate-400 tracking-wide">{ariaLabel}</p>
    </div>
  );
}

function MicIcon({ size = 40, className = '' }: { size?: number; className?: string }): ReactNode {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="currentColor"
      className={className}
      aria-hidden="true"
    >
      <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
      <path d="M5 11a1 1 0 0 1 2 0 5 5 0 0 0 10 0 1 1 0 0 1 2 0 7 7 0 0 1-6 6.93V21a1 1 0 0 1-2 0v-3.07A7 7 0 0 1 5 11z" />
    </svg>
  );
}
