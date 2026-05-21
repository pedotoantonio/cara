// SVG donut for "X di Y fatti oggi" style indicators.
//
// Stroke-based ring: outer track + filled arc whose dasharray animates
// when `value` changes. Center slot shows the numeric ratio + an
// optional caption. Kept dependency-free (no chart lib).

import { useEffect, useState } from 'react';

export interface ProgressRingProps {
  /** 0..1 — clamped. */
  value: number;
  /** Pixel size of the square viewport. */
  size?: number;
  /** Ring thickness. Default 8 looks balanced at 96px. */
  thickness?: number;
  /** Color of the filled arc — defaults to the theme accent. */
  trackColor?: string;
  fillColor?: string;
  /** Text shown in the center, large. */
  primaryLabel?: string;
  /** Smaller text under the primary label. */
  caption?: string;
  className?: string;
}

export function ProgressRing({
  value,
  size = 96,
  thickness = 8,
  trackColor = 'rgba(0,0,0,0.08)',
  fillColor = 'currentColor',
  primaryLabel,
  caption,
  className,
}: ProgressRingProps) {
  const clamped = Math.max(0, Math.min(1, value));
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  // Animate from previous → new over 350ms so completing a task feels
  // celebratory instead of snappy.
  const [animated, setAnimated] = useState(clamped);
  useEffect(() => {
    const id = window.requestAnimationFrame(() => setAnimated(clamped));
    return () => window.cancelAnimationFrame(id);
  }, [clamped]);

  const dashOffset = circumference * (1 - animated);

  return (
    <div
      className={className}
      style={{ width: size, height: size, position: 'relative', display: 'inline-block' }}
      role="img"
      aria-label={primaryLabel ? `${primaryLabel}${caption ? ', ' + caption : ''}` : `${Math.round(clamped * 100)} percento`}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={trackColor}
          strokeWidth={thickness}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={fillColor}
          strokeWidth={thickness}
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 350ms ease-out' }}
        />
      </svg>
      {(primaryLabel || caption) && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            lineHeight: 1,
            gap: 2,
            pointerEvents: 'none',
          }}
        >
          {primaryLabel && (
            <span className="font-display text-fg" style={{ fontSize: Math.max(14, size * 0.22) }}>
              {primaryLabel}
            </span>
          )}
          {caption && (
            <span className="text-fg-muted" style={{ fontSize: Math.max(10, size * 0.11) }}>
              {caption}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
