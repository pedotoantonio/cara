/**
 * CARA's animated face — pure SVG + CSS, no extra deps.
 *
 * Two independent dimensions (Lumo-style):
 *   - `energy`:  what CARA is doing (idle, listening, thinking, speaking, sleep, ...)
 *   - `emotion`: what CARA feels about it (neutral, happy, sad, love, surprised, ...)
 *
 * The two combine: e.g. (speaking, happy) is a happy speaker, (idle, love) is
 * a quiet lover gaze.
 *
 * Mai fermo (Cozmo/Vector principle):
 *   - Random blinks every 2.5–6 s in any non-sleeping state.
 *   - Subtle "look around" eye drift in idle state.
 *   - Squash-and-stretch on emotion transition.
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { onSpeakEvent } from '../lib/speech';

export type EnergyState =
  | 'idle'
  | 'listening'
  | 'sensing'        // hears ambient audio but no speech yet
  | 'thinking'
  | 'speaking'
  | 'sleeping'       // light sleep, eyes half-closed
  | 'deep_sleep'    // closed + Z particles (handled in step 33)
  | 'waking_up'     // transition out of sleep
  | 'focused';      // long task / sleep cycle

export type Emotion =
  | 'neutral'
  | 'happy'
  | 'joyful'
  | 'love'
  | 'surprised'
  | 'thoughtful'
  | 'confused'
  | 'sad'
  | 'embarrassed'
  | 'ironic'
  | 'sleepy'
  | 'error';

// Backward-compat alias used by existing callers.
export type FaceState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'happy' | 'sad';

interface CaraFaceProps {
  /** New API: energy state. */
  energy?: EnergyState;
  /** New API: emotion overlay. */
  emotion?: Emotion;
  /** Legacy single-axis prop. If set, mapped to (energy, emotion). */
  state?: FaceState;
  size?: number;
  className?: string;
}

const SKIN = '#10b981';
const SKIN_DARK = '#065f46';
const EYE = '#0f172a';

const LEGACY_MAP: Record<FaceState, { energy: EnergyState; emotion: Emotion }> = {
  idle: { energy: 'idle', emotion: 'neutral' },
  listening: { energy: 'listening', emotion: 'neutral' },
  thinking: { energy: 'thinking', emotion: 'thoughtful' },
  speaking: { energy: 'speaking', emotion: 'neutral' },
  happy: { energy: 'idle', emotion: 'happy' },
  sad: { energy: 'idle', emotion: 'sad' },
};

interface EyeGeom {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
  /** Optional explicit SVG path that replaces the ellipse (used by `love`, `error`). */
  path?: string;
}

interface BrowGeom {
  d: string;
  /** Hide brows when undefined (love/sleep states drop them). */
  visible: boolean;
}

interface FrameGeom {
  left: EyeGeom;
  right: EyeGeom;
  brows: { left: BrowGeom; right: BrowGeom };
  /** Highlight (small white dot) intensity 0–1; love/joy boost it. */
  sparkle: number;
}

// Pure functions: state → geometry. Keeps the JSX clean.

function emotionGeometry(emotion: Emotion): FrameGeom {
  // Default neutral baseline. Eyes centred, gentle highlight.
  const base: FrameGeom = {
    left: { cx: 36, cy: 46, rx: 6, ry: 9 },
    right: { cx: 64, cy: 46, rx: 6, ry: 9 },
    brows: {
      left: { d: 'M 28 30 Q 36 27 44 30', visible: true },
      right: { d: 'M 56 30 Q 64 27 72 30', visible: true },
    },
    sparkle: 0.4,
  };

  switch (emotion) {
    case 'happy':
      // Eyes squint into a U-shape (closed-eye smile).
      return {
        ...base,
        left: { ...base.left, ry: 4, path: 'M 30 46 Q 36 53 42 46' },
        right: { ...base.right, ry: 4, path: 'M 58 46 Q 64 53 70 46' },
        brows: {
          left: { d: 'M 28 28 Q 36 26 44 28', visible: true },
          right: { d: 'M 56 28 Q 64 26 72 28', visible: true },
        },
        sparkle: 0.7,
      };
    case 'joyful':
      // Big sparkly eyes, brows raised.
      return {
        ...base,
        left: { ...base.left, rx: 7, ry: 10 },
        right: { ...base.right, rx: 7, ry: 10 },
        brows: {
          left: { d: 'M 28 26 Q 36 22 44 26', visible: true },
          right: { d: 'M 56 26 Q 64 22 72 26', visible: true },
        },
        sparkle: 1,
      };
    case 'love':
      // Heart-shaped eyes, no brows.
      return {
        ...base,
        left: {
          ...base.left,
          path:
            'M36 41 c -3 -5 -10 -1 -10 4 c 0 5 10 10 10 10 c 0 0 10 -5 10 -10 c 0 -5 -7 -9 -10 -4 z',
        },
        right: {
          ...base.right,
          path:
            'M64 41 c -3 -5 -10 -1 -10 4 c 0 5 10 10 10 10 c 0 0 10 -5 10 -10 c 0 -5 -7 -9 -10 -4 z',
        },
        brows: { left: { d: '', visible: false }, right: { d: '', visible: false } },
        sparkle: 1,
      };
    case 'surprised':
      // Wide eyes, small pupils (handled by ratio), brows up.
      return {
        ...base,
        left: { ...base.left, rx: 8, ry: 11 },
        right: { ...base.right, rx: 8, ry: 11 },
        brows: {
          left: { d: 'M 28 24 Q 36 21 44 24', visible: true },
          right: { d: 'M 56 24 Q 64 21 72 24', visible: true },
        },
        sparkle: 0.6,
      };
    case 'thoughtful':
      return {
        ...base,
        // Eyes glance up-right slightly.
        left: { ...base.left, cx: 38, cy: 44 },
        right: { ...base.right, cx: 66, cy: 44 },
        brows: {
          left: { d: 'M 28 30 Q 34 26 44 32', visible: true },
          right: { d: 'M 56 30 Q 62 26 72 32', visible: true },
        },
        sparkle: 0.3,
      };
    case 'confused':
      return {
        ...base,
        // Asymmetric eyes — left bigger, right smaller.
        left: { ...base.left, rx: 7, ry: 10 },
        right: { ...base.right, rx: 5, ry: 7 },
        brows: {
          left: { d: 'M 28 26 Q 36 24 44 30', visible: true },
          right: { d: 'M 56 32 Q 64 26 72 30', visible: true },
        },
        sparkle: 0.3,
      };
    case 'sad':
      return {
        ...base,
        // Eyes droop, brows angled inward-up (worried).
        left: { ...base.left, cy: 50, ry: 7 },
        right: { ...base.right, cy: 50, ry: 7 },
        brows: {
          left: { d: 'M 28 32 Q 36 28 44 34', visible: true },
          right: { d: 'M 56 34 Q 64 28 72 32', visible: true },
        },
        sparkle: 0.2,
      };
    case 'embarrassed':
      // Eyes glance down, small.
      return {
        ...base,
        left: { ...base.left, cy: 50, ry: 5 },
        right: { ...base.right, cy: 50, ry: 5 },
        brows: {
          left: { d: 'M 28 32 Q 36 30 44 32', visible: true },
          right: { d: 'M 56 32 Q 64 30 72 32', visible: true },
        },
        sparkle: 0.3,
      };
    case 'ironic':
      // One brow up, eye slight squint on the same side.
      return {
        ...base,
        left: { ...base.left, ry: 7 },
        brows: {
          left: { d: 'M 28 32 Q 36 32 44 32', visible: true },
          right: { d: 'M 56 24 Q 64 21 72 26', visible: true },
        },
        sparkle: 0.5,
      };
    case 'sleepy':
      return {
        ...base,
        left: { ...base.left, ry: 3, cy: 48 },
        right: { ...base.right, ry: 3, cy: 48 },
        brows: { left: { d: '', visible: false }, right: { d: '', visible: false } },
        sparkle: 0.1,
      };
    case 'error':
      // Eyes become an X.
      return {
        ...base,
        left: {
          ...base.left,
          path: 'M 30 40 L 42 52 M 42 40 L 30 52',
        },
        right: {
          ...base.right,
          path: 'M 58 40 L 70 52 M 70 40 L 58 52',
        },
        brows: { left: { d: '', visible: false }, right: { d: '', visible: false } },
        sparkle: 0,
      };
    case 'neutral':
    default:
      return base;
  }
}

/** Apply energy-state transforms ON TOP of the emotion baseline. */
function applyEnergy(geom: FrameGeom, energy: EnergyState, blink: boolean, drift: { x: number; y: number }): FrameGeom {
  let g = geom;
  if (blink) {
    g = {
      ...g,
      left: { ...g.left, ry: 1, path: undefined },
      right: { ...g.right, ry: 1, path: undefined },
    };
  }
  if (energy === 'thinking') {
    // Eyes glance up-left, slight squint.
    g = {
      ...g,
      left: { ...g.left, cy: g.left.cy - 4, cx: g.left.cx - 2 },
      right: { ...g.right, cy: g.right.cy - 4, cx: g.right.cx - 2 },
    };
  } else if (energy === 'listening') {
    // Wide and attentive.
    g = {
      ...g,
      left: { ...g.left, rx: g.left.rx + 1, ry: g.left.ry + 1 },
      right: { ...g.right, rx: g.right.rx + 1, ry: g.right.ry + 1 },
    };
  } else if (energy === 'sensing') {
    // Subtle attention — left brow up.
    g = {
      ...g,
      brows: {
        ...g.brows,
        right: { ...g.brows.right, d: 'M 56 26 Q 64 22 72 26' },
      },
    };
  } else if (energy === 'sleeping') {
    g = {
      ...g,
      left: { ...g.left, ry: 2, path: undefined },
      right: { ...g.right, ry: 2, path: undefined },
      brows: { left: { d: '', visible: false }, right: { d: '', visible: false } },
    };
  } else if (energy === 'deep_sleep') {
    g = {
      ...g,
      left: { ...g.left, path: 'M 30 46 Q 36 48 42 46' },
      right: { ...g.right, path: 'M 58 46 Q 64 48 70 46' },
      brows: { left: { d: '', visible: false }, right: { d: '', visible: false } },
    };
  }
  // Idle drift: eyes wander a couple of pixels around their target.
  if (energy === 'idle' || energy === 'sensing') {
    g = {
      ...g,
      left: { ...g.left, cx: g.left.cx + drift.x, cy: g.left.cy + drift.y },
      right: { ...g.right, cx: g.right.cx + drift.x, cy: g.right.cy + drift.y },
    };
  }
  return g;
}

export function CaraFace({
  energy: energyProp,
  emotion: emotionProp,
  state,
  size = 96,
  className = '',
}: CaraFaceProps) {
  const { energy, emotion } = useMemo(() => {
    if (energyProp || emotionProp) {
      return { energy: energyProp ?? 'idle', emotion: emotionProp ?? 'neutral' };
    }
    if (state && state in LEGACY_MAP) return LEGACY_MAP[state];
    return { energy: 'idle' as EnergyState, emotion: 'neutral' as Emotion };
  }, [energyProp, emotionProp, state]);

  const [blink, setBlink] = useState(false);
  const [drift, setDrift] = useState({ x: 0, y: 0 });

  // Random blinks (any non-sleep state)
  useEffect(() => {
    if (energy === 'sleeping' || energy === 'deep_sleep') return;
    let cancelled = false;
    function loop() {
      if (cancelled) return;
      const wait = 2500 + Math.random() * 3500;
      const handle = setTimeout(() => {
        if (cancelled) return;
        setBlink(true);
        setTimeout(() => {
          if (cancelled) return;
          setBlink(false);
          loop();
        }, 130);
      }, wait);
      cancelHandle = handle;
    }
    let cancelHandle: ReturnType<typeof setTimeout> | undefined;
    loop();
    return () => {
      cancelled = true;
      if (cancelHandle) clearTimeout(cancelHandle);
    };
  }, [energy]);

  // Idle drift: eyes look around 2-3 px in a random direction every ~3-6s
  useEffect(() => {
    if (energy !== 'idle' && energy !== 'sensing') {
      setDrift({ x: 0, y: 0 });
      return;
    }
    let cancelled = false;
    function loop() {
      if (cancelled) return;
      const wait = 3000 + Math.random() * 4000;
      const handle = setTimeout(() => {
        if (cancelled) return;
        setDrift({
          x: (Math.random() - 0.5) * 4,
          y: (Math.random() - 0.5) * 3,
        });
        loop();
      }, wait);
      cancelHandle = handle;
    }
    let cancelHandle: ReturnType<typeof setTimeout> | undefined;
    loop();
    return () => {
      cancelled = true;
      if (cancelHandle) clearTimeout(cancelHandle);
    };
  }, [energy]);

  // Speaking: hybrid pulsation
  //   - Continuous gentle sine breathing (so the face never looks frozen
  //     between words, even when no boundary events arrive).
  //   - On every `onboundary` from speechSynthesis, an extra short snap
  //     ramp adds 30% amplitude on top, in sync with each spoken word.
  const [speakPulse, setSpeakPulse] = useState(0);
  const wordBoostRef = useRef<number>(0); // decays towards 0
  const wordBoostUntilRef = useRef<number>(0);
  const animRef = useRef<number | null>(null);

  useEffect(() => {
    if (energy !== 'speaking') {
      setSpeakPulse(0);
      return;
    }
    const t0 = performance.now();
    function frame(now: number) {
      const dt = (now - t0) / 1000;
      const sine = 0.5 + 0.5 * Math.sin(dt * 6.0) * Math.cos(dt * 1.7);
      // Word boost: ramp 0→1 over 90ms after a boundary event, then decay.
      let boost = 0;
      if (wordBoostUntilRef.current > now) {
        const remain = (wordBoostUntilRef.current - now) / 240; // total 240ms decay
        boost = Math.max(0, Math.min(1, remain));
      }
      wordBoostRef.current = boost;
      const v = Math.min(1, sine * 0.7 + boost * 0.5);
      setSpeakPulse(v);
      animRef.current = requestAnimationFrame(frame);
    }
    animRef.current = requestAnimationFrame(frame);
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [energy]);

  // Subscribe to TTS boundary events globally (not gated on `energy`) so the
  // face also wakes up if the caller forgets to switch to `speaking` first.
  useEffect(() => {
    return onSpeakEvent((ev) => {
      if (ev.type === 'pulse') {
        wordBoostUntilRef.current = performance.now() + 240;
      }
    });
  }, []);

  const baseGeom = emotionGeometry(emotion);
  const geom = applyEnergy(baseGeom, energy, blink, drift);

  // While speaking, scale eye height by 0.85–1.05 with the pulse.
  const speakScale = energy === 'speaking' ? 0.85 + speakPulse * 0.2 : 1;

  function renderEye(g: EyeGeom) {
    if (g.path) {
      // For paths (love hearts, X errors), no transition that would mangle the d attribute.
      return (
        <path
          d={g.path}
          fill={emotion === 'error' ? 'none' : EYE}
          stroke={emotion === 'error' ? EYE : 'none'}
          strokeWidth={emotion === 'error' ? 4 : 0}
          strokeLinecap="round"
        />
      );
    }
    return (
      <ellipse
        cx={g.cx}
        cy={g.cy}
        rx={g.rx}
        ry={g.ry * speakScale}
        fill={EYE}
        style={{ transition: 'all 220ms cubic-bezier(.4,.0,.2,1)' }}
      />
    );
  }

  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={`shrink-0 ${className}`}
      role="img"
      aria-label={`CARA ${energy}/${emotion}`}
    >
      <defs>
        <radialGradient id="caraSkin" cx="50%" cy="40%" r="60%">
          <stop offset="0%" stopColor={SKIN} />
          <stop offset="100%" stopColor={SKIN_DARK} />
        </radialGradient>
      </defs>

      {/* head */}
      <circle cx="50" cy="50" r="46" fill="url(#caraSkin)" />

      {/* brows */}
      {geom.brows.left.visible && geom.brows.left.d && (
        <path
          d={geom.brows.left.d}
          stroke={EYE}
          strokeWidth="3"
          strokeLinecap="round"
          fill="none"
          style={{ transition: 'd 240ms ease' }}
        />
      )}
      {geom.brows.right.visible && geom.brows.right.d && (
        <path
          d={geom.brows.right.d}
          stroke={EYE}
          strokeWidth="3"
          strokeLinecap="round"
          fill="none"
          style={{ transition: 'd 240ms ease' }}
        />
      )}

      {/* eyes */}
      {renderEye(geom.left)}
      {renderEye(geom.right)}

      {/* highlights / sparkle */}
      {geom.sparkle > 0 && !blink && !geom.left.path && (
        <>
          <circle
            cx={geom.left.cx + 1.5}
            cy={geom.left.cy - 3}
            r={1.4}
            fill="#fff"
            opacity={geom.sparkle}
          />
          <circle
            cx={geom.right.cx + 1.5}
            cy={geom.right.cy - 3}
            r={1.4}
            fill="#fff"
            opacity={geom.sparkle}
          />
        </>
      )}

      {/* thinking dot */}
      {energy === 'thinking' && (
        <circle cx="80" cy="22" r="4" fill={EYE}>
          <animate attributeName="opacity" values="0.2;1;0.2" dur="1.4s" repeatCount="indefinite" />
        </circle>
      )}

      {/* sleep "Z" — minimal, full system arrives in step 33 with canvas particles */}
      {energy === 'deep_sleep' && (
        <text x="74" y="28" fontSize="10" fill={EYE} fontFamily="serif">
          Z
        </text>
      )}
    </svg>
  );
}
