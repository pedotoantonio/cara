/**
 * Audio level meter — horizontal bar that shows in real time what the
 * microphone is actually picking up. Solves the #1 voice-UX complaint
 * ("rimane in attesa ma non capisce nulla") by giving the user
 * unambiguous evidence of mic activity.
 *
 * Visual states (driven by `db` prop):
 *
 *   db ≤ -55  → red flat bar + "Non sento il microfono"
 *   db ≤ -45  → amber bar + "Parla più forte"
 *   db ≥ -45  → green bar, scales with level
 *
 * Internally we keep a separate `peak` value that decays slowly so
 * the user perceives the loudest recent moment, not just the
 * instantaneous level (analogous to the old VU-meter peak indicator).
 *
 * The bar is `role="meter"` for screen readers and the `aria-valuenow`
 * is updated coarsely (~5 Hz) to avoid AT chatter.
 */

import { useEffect, useRef, useState } from 'react';

interface AudioLevelMeterProps {
  /** Current dBFS level, typically -60..0. */
  db: number;
  /** Normalised 0..1 level (so consumers can use the same value). */
  level: number;
  /** Show / hide. We unmount when false to free the AnalyserNode. */
  active: boolean;
  /** Optional width tweak (px). Default ~256. */
  width?: number;
}

export function AudioLevelMeter({ db, level, active, width = 256 }: AudioLevelMeterProps) {
  // Peak with slow decay (-3 dB / 250 ms ≈ 12 dB/s, classic VU feel).
  const peakRef = useRef<number>(0);
  const [peak, setPeak] = useState<number>(0);
  const lastPeakUpdateAt = useRef<number>(performance.now());
  const lastAriaUpdate = useRef<number>(0);
  const [aria, setAria] = useState<number>(0);

  useEffect(() => {
    if (!active) return;
    const now = performance.now();
    const dt = (now - lastPeakUpdateAt.current) / 1000;
    lastPeakUpdateAt.current = now;
    // Exponential decay so it never sticks.
    const decayedPeak = Math.max(0, peakRef.current - dt * 0.5);
    const newPeak = Math.max(decayedPeak, level);
    peakRef.current = newPeak;
    setPeak(newPeak);

    if (now - lastAriaUpdate.current > 200) {
      lastAriaUpdate.current = now;
      setAria(Math.round(level * 100));
    }
  }, [level, active]);

  if (!active) return null;

  // Color & label by current dB.
  let color = 'bg-emerald-500';
  let hint = '';
  if (db <= -55) {
    color = 'bg-rose-500';
    hint = 'Non sento il microfono';
  } else if (db <= -45) {
    color = 'bg-amber-500';
    hint = 'Parla più forte';
  } else if (db <= -38) {
    color = 'bg-amber-400';
    hint = 'Ti sento, ma piano';
  } else {
    color = 'bg-emerald-500';
    hint = 'Ti sto sentendo';
  }

  const filledPct = Math.max(2, Math.round(level * 100));
  const peakPct = Math.max(2, Math.round(peak * 100));

  return (
    <div
      className="flex flex-col items-center gap-1"
      role="meter"
      aria-label="Livello microfono"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={aria}
    >
      <div
        className="relative h-3 rounded-full bg-bg-soft border border-fg/10 overflow-hidden"
        style={{ width }}
      >
        {/* tick marks every 25% — give the user a sense of scale */}
        {[25, 50, 75].map((p) => (
          <span
            key={p}
            className="absolute top-0 bottom-0 w-px bg-fg/15"
            style={{ left: `${p}%` }}
            aria-hidden="true"
          />
        ))}
        {/* main filled bar */}
        <div
          className={`absolute inset-y-0 left-0 ${color} transition-[width,background-color] duration-75 ease-out`}
          style={{ width: `${filledPct}%` }}
        />
        {/* peak indicator (1px) — slow decay */}
        <div
          className="absolute inset-y-0 w-0.5 bg-white/80"
          style={{ left: `calc(${peakPct}% - 1px)` }}
          aria-hidden="true"
        />
      </div>
      <span className="text-xs text-fg-muted tabular-nums select-none">
        {hint}
      </span>
    </div>
  );
}

export default AudioLevelMeter;
