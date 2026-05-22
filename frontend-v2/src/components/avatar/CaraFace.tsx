/**
 * CaraFace — "atomo neurale" CARA, organismo SVG astratto.
 *
 * Sostituisce il vecchio volto antropomorfo (eyes + mouth) con un
 * organismo grafico astratto: core energetico al centro, 3 orbite
 * ellittiche con nodi neurali, membrana esterna luminosa, particelle
 * dati in flusso. NIENTE volto, NIENTE testo, NIENTE forme umane.
 *
 * Le emozioni NON cambiano "facce" ma modulano parametri continui
 * (tempo, spazio, colore, densità, coerenza) — lo stile è quello del
 * prompt CARA Avatar v2 (20/05/2026). API invariata rispetto al
 * componente legacy: `energy`, `emotion`, `state` (compat), `size`,
 * `className`. Tutti i call-site (Wall, HomePage, Chat, FaceLab,
 * Menu, FX) continuano a funzionare senza modifiche.
 *
 * Architettura: SVG + CSS keyframes + CSS variables. Le variabili
 * sono settate da React in base al profilo emozione, le keyframe le
 * leggono. Le transizioni fra emozioni avvengono via `transition`
 * CSS sui valori interpolabili — durata 800 ms cubic-bezier.
 */

import { useEffect, useMemo, useRef, useState } from 'react';

// onSpeakEvent → v1 lip-sync helper. In v2 verrà cablato dal lib/tts player
// quando l'audio_chunk Piper viene riprodotto. Stub silenzioso per ora.
type SpeakEvent = { type: 'pulse' | 'idle'; word?: string; charIndex?: number };
const onSpeakEvent = (_cb: (e: SpeakEvent) => void): (() => void) => () => {};


// ── API types (invariati rispetto al legacy) ──────────────────────

export type EnergyState =
  | 'idle'
  | 'listening'
  | 'sensing'
  | 'thinking'
  | 'speaking'
  | 'sleeping'
  | 'deep_sleep'
  | 'waking_up'
  | 'focused';

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

export type FaceState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'happy' | 'sad';

interface CaraFaceProps {
  /** Cosa CARA sta facendo. */
  energy?: EnergyState;
  /** Cosa CARA sente. */
  emotion?: Emotion;
  /** Legacy single-axis state. */
  state?: FaceState;
  size?: number;
  className?: string;
}

const LEGACY_MAP: Record<FaceState, { energy: EnergyState; emotion: Emotion }> = {
  idle:      { energy: 'idle',      emotion: 'neutral' },
  listening: { energy: 'listening', emotion: 'neutral' },
  thinking:  { energy: 'thinking',  emotion: 'thoughtful' },
  speaking:  { energy: 'speaking',  emotion: 'neutral' },
  happy:     { energy: 'idle',      emotion: 'happy' },
  sad:       { energy: 'idle',      emotion: 'sad' },
};


// ── Emotion profile — firma parametrica per ogni stato ────────────

interface EmotionProfile {
  coreInner: string;
  coreOuter: string;
  corePulseSec: number;
  corePulseAmp: number;
  doubleBeat: boolean;

  orbitColor: string;
  orbitRotateSec: [number, number, number];

  membraneColor: string;
  membraneScale: number;
  membraneBreatheSec: number;

  nodeColor: string;
  nodeRadius: number;
  nodeMode: 'steady' | 'cascade' | 'stochastic' | 'sequence' | 'fused' | 'pulsing';

  particleColor: string;
  particleCount: number;
  particleSpeed: number;
}


const PROFILES: Record<Emotion, EmotionProfile> = {
  // ── NEUTRO ─────────────────────────────────────────────────────
  neutral: {
    coreInner: '#fcd34d', coreOuter: '#f59e0b',
    corePulseSec: 3.0, corePulseAmp: 1.06, doubleBeat: false,
    orbitColor: '#06b6d4',
    orbitRotateSec: [50, 60, 45],
    membraneColor: '#3b82f6',
    membraneScale: 1.0, membraneBreatheSec: 4.0,
    nodeColor: '#67e8f9', nodeRadius: 3.2, nodeMode: 'steady',
    particleColor: '#a5f3fc', particleCount: 1, particleSpeed: 1.0,
  },
  // ── CALMA — happy = calma serenità ─────────────────────────────
  happy: {
    coreInner: '#a7f3d0', coreOuter: '#5eead4',
    corePulseSec: 4.8, corePulseAmp: 1.05, doubleBeat: false,
    orbitColor: '#5eead4',
    orbitRotateSec: [90, 90, 90],
    membraneColor: '#a7f3d0',
    membraneScale: 1.05, membraneBreatheSec: 6.0,
    nodeColor: '#5eead4', nodeRadius: 3.5, nodeMode: 'steady',
    particleColor: '#99f6e4', particleCount: 1, particleSpeed: 0.6,
  },
  // ── GIOIA — joyful (sincrona, dilatata, particelle moltiplicate) ─
  joyful: {
    coreInner: '#fef08a', coreOuter: '#fbbf24',
    corePulseSec: 1.2, corePulseAmp: 1.18, doubleBeat: false,
    orbitColor: '#a5f3fc',
    orbitRotateSec: [15, 15, 15],
    membraneColor: '#93c5fd',
    membraneScale: 1.15, membraneBreatheSec: 2.5,
    nodeColor: '#fde047', nodeRadius: 4.0, nodeMode: 'cascade',
    particleColor: '#fde68a', particleCount: 4, particleSpeed: 1.6,
  },
  // ── AMORE — rosa caldo, doppio battito ─────────────────────────
  love: {
    coreInner: '#fda4af', coreOuter: '#f43f5e',
    corePulseSec: 1.5, corePulseAmp: 1.14, doubleBeat: true,
    orbitColor: '#e879f9',
    orbitRotateSec: [55, 50, 60],
    membraneColor: '#fda4af',
    membraneScale: 1.20, membraneBreatheSec: 5.0,
    nodeColor: '#f472b6', nodeRadius: 3.8, nodeMode: 'fused',
    particleColor: '#fbcfe8', particleCount: 2, particleSpeed: 0.5,
  },
  // ── SORPRESA — flash bianco + onda d'urto ───────────────────────
  surprised: {
    coreInner: '#ffffff', coreOuter: '#fde68a',
    corePulseSec: 0.6, corePulseAmp: 1.30, doubleBeat: false,
    orbitColor: '#fef3c7',
    orbitRotateSec: [22, 18, 26],
    membraneColor: '#fcd34d',
    membraneScale: 1.30, membraneBreatheSec: 1.4,
    nodeColor: '#fef9c3', nodeRadius: 4.4, nodeMode: 'pulsing',
    particleColor: '#fef9c3', particleCount: 3, particleSpeed: 1.4,
  },
  // ── PENSIERO — viola elettrico ─────────────────────────────────
  thoughtful: {
    coreInner: '#c4b5fd', coreOuter: '#8b5cf6',
    corePulseSec: 1.6, corePulseAmp: 1.10, doubleBeat: false,
    orbitColor: '#a78bfa',
    orbitRotateSec: [30, 26, 34],
    membraneColor: '#7c3aed',
    membraneScale: 0.97, membraneBreatheSec: 5.5,
    nodeColor: '#a78bfa', nodeRadius: 3.5, nodeMode: 'sequence',
    particleColor: '#c4b5fd', particleCount: 2, particleSpeed: 1.1,
  },
  // ── PENSIERO + desync — confused ───────────────────────────────
  confused: {
    coreInner: '#ddd6fe', coreOuter: '#a78bfa',
    corePulseSec: 1.4, corePulseAmp: 1.12, doubleBeat: false,
    orbitColor: '#c4b5fd',
    orbitRotateSec: [22, 38, 14],
    membraneColor: '#a78bfa',
    membraneScale: 0.98, membraneBreatheSec: 5.0,
    nodeColor: '#a78bfa', nodeRadius: 3.4, nodeMode: 'stochastic',
    particleColor: '#ddd6fe', particleCount: 2, particleSpeed: 1.2,
  },
  // ── DISPIACERE / risonanza empatica — sad ──────────────────────
  sad: {
    coreInner: '#3b82f6', coreOuter: '#1e40af',
    corePulseSec: 4.0, corePulseAmp: 1.03, doubleBeat: false,
    orbitColor: '#1e3a8a',
    orbitRotateSec: [80, 85, 90],
    membraneColor: '#1e40af',
    membraneScale: 0.92, membraneBreatheSec: 6.5,
    nodeColor: '#60a5fa', nodeRadius: 2.6, nodeMode: 'steady',
    particleColor: '#93c5fd', particleCount: 1, particleSpeed: 0.4,
  },
  // ── AMORE soft — embarrassed ───────────────────────────────────
  embarrassed: {
    coreInner: '#fecdd3', coreOuter: '#fb7185',
    corePulseSec: 2.2, corePulseAmp: 1.08, doubleBeat: false,
    orbitColor: '#f9a8d4',
    orbitRotateSec: [60, 58, 62],
    membraneColor: '#fecdd3',
    membraneScale: 1.06, membraneBreatheSec: 4.5,
    nodeColor: '#fda4af', nodeRadius: 3.2, nodeMode: 'pulsing',
    particleColor: '#fce7f3', particleCount: 1, particleSpeed: 0.7,
  },
  // ── CURIOSITÀ off-balance — ironic ──────────────────────────────
  ironic: {
    coreInner: '#67e8f9', coreOuter: '#06b6d4',
    corePulseSec: 1.5, corePulseAmp: 1.10, doubleBeat: false,
    orbitColor: '#22d3ee',
    orbitRotateSec: [25, 70, 35],
    membraneColor: '#0891b2',
    membraneScale: 0.96, membraneBreatheSec: 4.0,
    nodeColor: '#67e8f9', nodeRadius: 3.4, nodeMode: 'stochastic',
    particleColor: '#cffafe', particleCount: 2, particleSpeed: 1.0,
  },
  // ── DISPIACERE slow — sleepy ───────────────────────────────────
  sleepy: {
    coreInner: '#94a3b8', coreOuter: '#475569',
    corePulseSec: 6.0, corePulseAmp: 1.02, doubleBeat: false,
    orbitColor: '#475569',
    orbitRotateSec: [120, 130, 110],
    membraneColor: '#334155',
    membraneScale: 0.94, membraneBreatheSec: 8.0,
    nodeColor: '#64748b', nodeRadius: 2.4, nodeMode: 'steady',
    particleColor: '#94a3b8', particleCount: 1, particleSpeed: 0.3,
  },
  // ── ERROR — rosso contratto ─────────────────────────────────────
  error: {
    coreInner: '#fca5a5', coreOuter: '#dc2626',
    corePulseSec: 1.0, corePulseAmp: 1.20, doubleBeat: false,
    orbitColor: '#ef4444',
    orbitRotateSec: [18, 22, 14],
    membraneColor: '#991b1b',
    membraneScale: 0.94, membraneBreatheSec: 1.8,
    nodeColor: '#fca5a5', nodeRadius: 3.8, nodeMode: 'stochastic',
    particleColor: '#fecaca', particleCount: 2, particleSpeed: 1.5,
  },
};


// ── Energy modulators — multipliers su top del profilo emozione ──

interface EnergyMods {
  pulseSpeedMul: number;
  pulseAmpMul: number;
  orbitSpeedMul: number;
  membraneScaleMul: number;
  orbitColorOverride?: string;
  convergeParticles: boolean;
  forceNodeSequence: boolean;
}

const ENERGY_MODS: Record<EnergyState, EnergyMods> = {
  idle:       { pulseSpeedMul: 1.0,  pulseAmpMul: 1.0,  orbitSpeedMul: 1.0, membraneScaleMul: 1.0,  convergeParticles: false, forceNodeSequence: false },
  listening:  { pulseSpeedMul: 0.9,  pulseAmpMul: 1.1,  orbitSpeedMul: 1.0, membraneScaleMul: 1.02, convergeParticles: true,  forceNodeSequence: false },
  sensing:    { pulseSpeedMul: 1.0,  pulseAmpMul: 1.05, orbitSpeedMul: 1.0, membraneScaleMul: 1.01, convergeParticles: false, forceNodeSequence: false },
  thinking:   { pulseSpeedMul: 0.8,  pulseAmpMul: 1.0,  orbitSpeedMul: 0.8, membraneScaleMul: 0.99, orbitColorOverride: '#a78bfa', convergeParticles: false, forceNodeSequence: true },
  speaking:   { pulseSpeedMul: 0.55, pulseAmpMul: 1.3,  orbitSpeedMul: 0.9, membraneScaleMul: 1.03, convergeParticles: false, forceNodeSequence: false },
  sleeping:   { pulseSpeedMul: 2.5,  pulseAmpMul: 0.5,  orbitSpeedMul: 3.0, membraneScaleMul: 0.92, convergeParticles: false, forceNodeSequence: false },
  deep_sleep: { pulseSpeedMul: 4.0,  pulseAmpMul: 0.3,  orbitSpeedMul: 5.0, membraneScaleMul: 0.88, convergeParticles: false, forceNodeSequence: false },
  waking_up:  { pulseSpeedMul: 1.5,  pulseAmpMul: 0.8,  orbitSpeedMul: 1.5, membraneScaleMul: 0.97, convergeParticles: false, forceNodeSequence: false },
  focused:    { pulseSpeedMul: 0.85, pulseAmpMul: 1.1,  orbitSpeedMul: 0.7, membraneScaleMul: 0.98, convergeParticles: true,  forceNodeSequence: false },
};


// ── Component ─────────────────────────────────────────────────────


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

  // Surprise: flash bianco istantaneo ogni volta che l'emozione entra
  // nello stato `surprised`. Un useRef tiene traccia dell'ultimo
  // emotion per scatenare il flash solo sulla transizione di ingresso.
  const [shockwave, setShockwave] = useState(false);
  const prevEmotion = useRef(emotion);
  useEffect(() => {
    if (prevEmotion.current !== 'surprised' && emotion === 'surprised') {
      setShockwave(true);
      const t = setTimeout(() => setShockwave(false), 600);
      prevEmotion.current = emotion;
      return () => clearTimeout(t);
    }
    prevEmotion.current = emotion;
  }, [emotion]);

  // TTS speaking pulse — while energy=speaking, subscribe to the
  // speech bus and inflate the core for ~180ms per word pulse, just
  // like the legacy face did.
  const [ttsPulse, setTtsPulse] = useState(false);
  useEffect(() => {
    if (energy !== 'speaking') {
      setTtsPulse(false);
      return;
    }
    const off = onSpeakEvent((ev) => {
      if (ev.type === 'pulse') {
        setTtsPulse(true);
        setTimeout(() => setTtsPulse(false), 180);
      }
    });
    return off;
  }, [energy]);

  // Compose final CSS variables from emotion profile + energy mods.
  const profile = PROFILES[emotion];
  const mods = ENERGY_MODS[energy];

  const orbitColor = mods.orbitColorOverride ?? profile.orbitColor;
  const corePulseSec = (profile.corePulseSec * mods.pulseSpeedMul).toFixed(2);
  const corePulseScale = 1 + (profile.corePulseAmp - 1) * mods.pulseAmpMul;
  const membraneScale = profile.membraneScale * mods.membraneScaleMul;
  const orbitSec: [number, number, number] = [
    profile.orbitRotateSec[0] * mods.orbitSpeedMul,
    profile.orbitRotateSec[1] * mods.orbitSpeedMul,
    profile.orbitRotateSec[2] * mods.orbitSpeedMul,
  ];

  // If energy forces a node mode (thinking → sequence), it wins.
  const nodeMode = mods.forceNodeSequence ? 'sequence' : profile.nodeMode;

  const style: Record<string, string> = {
    '--core-inner':       profile.coreInner,
    '--core-outer':       profile.coreOuter,
    '--orbit-color':      orbitColor,
    '--membrane-color':   profile.membraneColor,
    '--node-color':       profile.nodeColor,
    '--particle-color':   profile.particleColor,
    '--core-pulse-sec':   `${corePulseSec}s`,
    '--membrane-breathe-sec': `${profile.membraneBreatheSec.toFixed(2)}s`,
    '--orbit-1-sec':      `${orbitSec[0].toFixed(1)}s`,
    '--orbit-2-sec':      `${orbitSec[1].toFixed(1)}s`,
    '--orbit-3-sec':      `${orbitSec[2].toFixed(1)}s`,
    '--core-pulse-scale': corePulseScale.toFixed(3),
    '--membrane-scale':   membraneScale.toFixed(3),
    '--node-radius':      `${profile.nodeRadius.toFixed(2)}`,
    '--particle-speed':   `${profile.particleSpeed.toFixed(2)}`,
  };

  const cls = [
    'cara-atom',
    `cara-atom--node-${nodeMode}`,
    profile.doubleBeat && 'cara-atom--double-beat',
    mods.convergeParticles && 'cara-atom--converge',
    shockwave && 'cara-atom--shockwave',
    ttsPulse && 'cara-atom--tts-pulse',
    className,
  ].filter(Boolean).join(' ');

  return (
    <div
      className={cls}
      style={{ ...(style as React.CSSProperties), width: size, height: size }}
      role="img"
      aria-label={`CARA — ${emotion}, ${energy}`}
    >
      <CaraAtomStyles />
      <svg viewBox="0 0 200 200" className="cara-atom__svg" preserveAspectRatio="xMidYMid meet">
        <defs>
          <radialGradient id="cara-core-grad" cx="50%" cy="50%" r="50%">
            <stop offset="0%"  stopColor="var(--core-inner)" stopOpacity="1" />
            <stop offset="55%" stopColor="var(--core-outer)" stopOpacity="0.95" />
            <stop offset="100%" stopColor="var(--core-outer)" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="cara-membrane-grad" cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stopColor="var(--membrane-color)" stopOpacity="0" />
            <stop offset="65%"  stopColor="var(--membrane-color)" stopOpacity="0.18" />
            <stop offset="85%"  stopColor="var(--membrane-color)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="var(--membrane-color)" stopOpacity="0" />
          </radialGradient>
          <filter id="cara-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Everything is wrapped in a single `translate(100,100)` so all
            inner coordinates are around (0,0). CSS rotations on the
            orbit groups then naturally pivot around the visual center
            — no `transform-origin`/`transform-box` gymnastics, no
            cross-browser surprises, no de-sync between orbits. */}
        <g transform="translate(100 100)">

          {/* Membrane — outer luminous skin */}
          <g className="cara-atom__membrane">
            <circle cx="0" cy="0" r="92" fill="url(#cara-membrane-grad)" />
            <circle cx="0" cy="0" r="86" fill="none"
                    stroke="var(--membrane-color)" strokeOpacity="0.35"
                    strokeWidth="0.6" />
          </g>

          {/* Three orbits — each one a self-rotating group, all
              spinning around the SAME (0,0) point so they share a
              perfect common nucleus. */}
          <g className="cara-atom__orbit cara-atom__orbit--1">
            <Orbit rx={70} ry={28} tilt={0}   nodes={3} particles={1} />
          </g>
          <g className="cara-atom__orbit cara-atom__orbit--2">
            <Orbit rx={70} ry={28} tilt={60}  nodes={3} particles={1} />
          </g>
          <g className="cara-atom__orbit cara-atom__orbit--3">
            <Orbit rx={70} ry={28} tilt={-60} nodes={2} particles={2} />
          </g>

          {/* Free swarm of particles around the core */}
          <ParticleSwarm count={profile.particleCount} />

          {/* Core — the consciousness */}
          <g className="cara-atom__core">
            <circle cx="0" cy="0" r="22" fill="url(#cara-core-grad)" filter="url(#cara-glow)" />
            <circle cx="0" cy="0" r="13"
                    fill="var(--core-inner)"
                    stroke="var(--core-outer)" strokeWidth="1.2" strokeOpacity="0.9" />
            <g className="cara-atom__glyph" stroke="var(--core-outer)" strokeOpacity="0.55"
               strokeWidth="0.7" strokeLinecap="round" fill="none">
              <line x1="-7" y1="0"  x2="7"  y2="0"  />
              <line x1="0"  y1="-7" x2="0"  y2="7"  />
              <circle cx="-6" cy="-6" r="0.9" fill="var(--core-outer)" stroke="none" />
              <circle cx="6"  cy="-6" r="0.9" fill="var(--core-outer)" stroke="none" />
              <circle cx="-6" cy="6"  r="0.9" fill="var(--core-outer)" stroke="none" />
              <circle cx="6"  cy="6"  r="0.9" fill="var(--core-outer)" stroke="none" />
            </g>
          </g>

          {/* Shockwave overlay — only on surprised transition */}
          {shockwave && (
            <circle className="cara-atom__shockwave-ring"
                    cx="0" cy="0" r="20" fill="none"
                    stroke="#ffffff" strokeOpacity="0.8" strokeWidth="2" />
          )}

        </g>
      </svg>
    </div>
  );
}


// ── Sub-components ────────────────────────────────────────────────


function Orbit({
  rx, ry, tilt, nodes, particles,
}: { rx: number; ry: number; tilt: number; nodes: number; particles: number }) {
  // All coordinates around (0,0). The visual centering happens in the
  // parent <g transform="translate(100 100)">.
  const nodePositions = useMemo(() => {
    const positions: { x: number; y: number; i: number }[] = [];
    for (let i = 0; i < nodes; i++) {
      const a = (i / nodes) * Math.PI * 2;
      positions.push({ x: rx * Math.cos(a), y: ry * Math.sin(a), i });
    }
    return positions;
  }, [rx, ry, nodes]);

  const particlePositions = useMemo(() => {
    const positions: { x: number; y: number; i: number }[] = [];
    for (let i = 0; i < particles; i++) {
      const a = ((i + 0.5) / particles) * Math.PI * 2;
      positions.push({ x: rx * Math.cos(a), y: ry * Math.sin(a), i });
    }
    return positions;
  }, [rx, ry, particles]);

  // `tilt` rotates around (0,0) — clean and unambiguous.
  return (
    <g transform={`rotate(${tilt})`}>
      <ellipse cx="0" cy="0" rx={rx} ry={ry}
               fill="none"
               stroke="var(--orbit-color)"
               strokeOpacity="0.45"
               strokeWidth="0.9"
               strokeDasharray="2 4" />
      {nodePositions.map((p) => (
        <circle
          key={`n${p.i}`}
          className="cara-atom__node"
          cx={p.x} cy={p.y}
          r={3.2}
          fill="var(--node-color)"
          filter="url(#cara-glow)"
          style={{ animationDelay: `${p.i * 0.25}s` }}
        />
      ))}
      {particlePositions.map((p) => (
        <circle
          key={`p${p.i}`}
          className="cara-atom__particle"
          cx={p.x} cy={p.y}
          r={1.6}
          fill="var(--particle-color)"
          opacity="0.85"
        />
      ))}
    </g>
  );
}


function ParticleSwarm({ count }: { count: number }) {
  // Centered around (0,0); parent <g translate(100,100)> places it
  // around the visible nucleus.
  const items = useMemo(() => {
    const N = Math.min(16, Math.max(0, count * 3));
    return Array.from({ length: N }, (_, i) => {
      const a = (i / N) * Math.PI * 2;
      const r = 35 + (i % 3) * 8;
      return {
        i,
        x: r * Math.cos(a),
        y: r * Math.sin(a),
        delay: (i % 4) * 0.4,
      };
    });
  }, [count]);
  return (
    <g className="cara-atom__swarm">
      {items.map((p) => (
        <circle
          key={p.i}
          cx={p.x} cy={p.y}
          r={0.9}
          fill="var(--particle-color)"
          opacity="0.7"
          style={{ animationDelay: `${p.delay}s` }}
        />
      ))}
    </g>
  );
}


// ── Scoped styles (injected once) ─────────────────────────────────


let _stylesInjected = false;
function CaraAtomStyles() {
  if (typeof document === 'undefined') return null;
  if (_stylesInjected) return null;
  _stylesInjected = true;
  const css = `
.cara-atom {
  position: relative;
  display: inline-block;
  user-select: none;
  --core-inner: #fcd34d;
  --core-outer: #f59e0b;
  --orbit-color: #06b6d4;
  --membrane-color: #3b82f6;
  --node-color: #67e8f9;
  --particle-color: #a5f3fc;
  --core-pulse-sec: 3s;
  --membrane-breathe-sec: 4s;
  --orbit-1-sec: 50s;
  --orbit-2-sec: 60s;
  --orbit-3-sec: 45s;
  --core-pulse-scale: 1.06;
  --membrane-scale: 1;
  --node-radius: 3.2;
  --particle-speed: 1;
  transition: filter 0.8s ease;
}
.cara-atom__svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}

.cara-atom__membrane {
  /* Coordinates inside the membrane group are already centred on
     (0,0) thanks to the parent translate(100,100). Default
     transform-origin = 0,0 = visual center. */
  animation: cara-breathe var(--membrane-breathe-sec) ease-in-out infinite;
  transition: opacity 0.8s ease;
}
@keyframes cara-breathe {
  0%, 100% { transform: scale(calc(var(--membrane-scale) * 0.985)); opacity: 0.85; }
  50%      { transform: scale(calc(var(--membrane-scale) * 1.015)); opacity: 1; }
}

/* All three orbits live inside the same translate(100 100) wrapper
   so their CSS rotation pivot is (0,0) = the shared nucleus. The
   transform-origin: 0 0 is the CSS default for SVG elements but we
   set it explicitly to make the contract obvious + bulletproof on
   older browsers. */
.cara-atom__orbit {
  transform-origin: 0 0;
}
.cara-atom__orbit--1 { animation: cara-spin var(--orbit-1-sec) linear infinite; }
.cara-atom__orbit--2 { animation: cara-spin-rev var(--orbit-2-sec) linear infinite; }
.cara-atom__orbit--3 { animation: cara-spin var(--orbit-3-sec) linear infinite; }
@keyframes cara-spin     { from { transform: rotate(0deg);   } to { transform: rotate(360deg); } }
@keyframes cara-spin-rev { from { transform: rotate(360deg); } to { transform: rotate(0deg);   } }

.cara-atom__node {
  /* Nodes pulse IN PLACE around their own centre, not around the
     atom nucleus. */
  transform-origin: center;
  transform-box: fill-box;
  animation: cara-node-soft 2.4s ease-in-out infinite;
  transition: fill 0.8s ease;
}
@keyframes cara-node-soft {
  0%, 100% { opacity: 0.85; transform: scale(1);    }
  50%      { opacity: 1;    transform: scale(1.12); }
}
.cara-atom--node-cascade    .cara-atom__node { animation: cara-node-cascade 1.6s ease-in-out infinite; }
.cara-atom--node-stochastic .cara-atom__node { animation: cara-node-stoch 0.9s steps(2, end) infinite; }
.cara-atom--node-sequence   .cara-atom__node { animation: cara-node-seq 2.0s ease-in-out infinite; }
.cara-atom--node-fused      .cara-atom__node { animation: cara-node-soft 3.5s ease-in-out infinite; }
.cara-atom--node-pulsing    .cara-atom__node { animation: cara-node-soft 1.0s ease-in-out infinite; }
@keyframes cara-node-cascade {
  0%, 100% { opacity: 0.65; transform: scale(0.9); }
  35%      { opacity: 1;    transform: scale(1.35); }
  60%      { opacity: 0.75; transform: scale(1.0); }
}
@keyframes cara-node-stoch {
  0%   { opacity: 0.5; transform: scale(0.9); }
  50%  { opacity: 1;   transform: scale(1.4); }
  100% { opacity: 0.7; transform: scale(1.0); }
}
@keyframes cara-node-seq {
  0%, 30%   { opacity: 0.55; transform: scale(0.95); }
  45%, 55%  { opacity: 1;    transform: scale(1.25); }
  70%, 100% { opacity: 0.65; transform: scale(1.0);  }
}

.cara-atom__particle {
  animation: cara-particle-blink calc(1.6s / var(--particle-speed)) ease-in-out infinite;
}
@keyframes cara-particle-blink {
  0%, 100% { opacity: 0.4; transform: scale(0.7); }
  50%      { opacity: 1;   transform: scale(1.3); }
}

.cara-atom__swarm circle {
  /* Swarm dots pulse around their own centre. */
  animation: cara-swarm-drift 6s ease-in-out infinite;
  transform-origin: center;
  transform-box: fill-box;
}
@keyframes cara-swarm-drift {
  0%, 100% { transform: scale(1);    opacity: 0.5; }
  50%      { transform: scale(1.4);  opacity: 1;   }
}

.cara-atom__core {
  /* Core sits at (0,0) inside the translated wrapper. Default
     transform-origin = 0,0 = the nucleus. */
  transform-origin: 0 0;
  animation: cara-core-pulse var(--core-pulse-sec) ease-in-out infinite;
  transition: filter 0.6s ease;
  filter: drop-shadow(0 0 6px var(--core-outer));
}
@keyframes cara-core-pulse {
  0%, 100% { transform: scale(1); }
  50%      { transform: scale(var(--core-pulse-scale)); }
}

.cara-atom--double-beat .cara-atom__core {
  animation: cara-core-heart var(--core-pulse-sec) ease-in-out infinite;
}
@keyframes cara-core-heart {
  0%   { transform: scale(1); }
  10%  { transform: scale(var(--core-pulse-scale)); }
  20%  { transform: scale(1); }
  30%  { transform: scale(var(--core-pulse-scale)); }
  40%  { transform: scale(1); }
  100% { transform: scale(1); }
}

.cara-atom--tts-pulse .cara-atom__core {
  transform: scale(calc(var(--core-pulse-scale) * 1.08));
  transition: transform 80ms ease-out;
}

.cara-atom--converge .cara-atom__particle,
.cara-atom--converge .cara-atom__swarm circle {
  animation-name: cara-converge;
}
@keyframes cara-converge {
  0%, 100% { opacity: 0.4;  transform: scale(1.0); }
  50%      { opacity: 0.95; transform: scale(0.7); }
}

.cara-atom__shockwave-ring {
  transform-origin: 0 0;
  animation: cara-shock 600ms ease-out forwards;
}
@keyframes cara-shock {
  0%   { transform: scale(1); opacity: 0.9; }
  100% { transform: scale(5); opacity: 0;   }
}
.cara-atom--shockwave .cara-atom__core {
  filter: drop-shadow(0 0 18px #ffffff);
}

.cara-atom__glyph {
  /* Inside the core group, glyph rotates around (0,0) = the same
     nucleus as everything else. */
  transform-origin: 0 0;
  animation: cara-spin 90s linear infinite;
}

@media (prefers-reduced-motion: reduce) {
  .cara-atom *,
  .cara-atom *::before,
  .cara-atom *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
  }
}
`;
  const tag = document.createElement('style');
  tag.setAttribute('data-cara-atom', '1');
  tag.textContent = css;
  document.head.appendChild(tag);
  return null;
}


export default CaraFace;
