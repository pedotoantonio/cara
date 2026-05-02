/**
 * CaraFaceFX — wraps <CaraFace> with optional ambient effects:
 *   - colored ring glow whose hue + intensity track (energy, emotion)
 *   - canvas particle layer (hearts for love, sparkles for joy, drops for sad,
 *     binary "matrix" for thinking)
 *
 * Both layers are pure presentational: state still flows in via props.
 * Particles render at 30 fps with `requestAnimationFrame`; the canvas is
 * resized to match the face size and is disabled cleanly on unmount.
 */

import { useEffect, useRef } from 'react';

import { CaraFace, type Emotion, type EnergyState } from './CaraFace';

interface CaraFaceFXProps {
  energy?: EnergyState;
  emotion?: Emotion;
  size?: number;
  className?: string;
  /** Disable particles to save battery / on small mini-avatars. */
  particles?: boolean;
  /** Disable glow ring (e.g. for the chat header where space is tight). */
  glow?: boolean;
  /** Enable touch/click gestures on the face (tap/swipe/long-press). */
  gestures?: boolean;
  /** Called on a single tap on the face. */
  onTap?: () => void;
  /** Called on a horizontal swipe ("carezza"). */
  onSwipe?: (direction: 'left' | 'right') => void;
  /** Called when the user holds the face for >800ms ("push-to-talk"). */
  onLongPress?: () => void;
  /** Called when the long press is released. */
  onLongPressEnd?: () => void;
}

interface ParticleSpec {
  /** how often new particles are spawned, ms between spawns. 0 = disabled. */
  spawnEveryMs: number;
  symbol: 'heart' | 'sparkle' | 'drop' | 'matrix' | 'question' | 'zzz';
  hue: string;
}

function particlesFor(emotion: Emotion, energy: EnergyState): ParticleSpec | null {
  if (energy === 'deep_sleep') return { spawnEveryMs: 1400, symbol: 'zzz', hue: '#94a3b8' };
  if (energy === 'thinking') return { spawnEveryMs: 220, symbol: 'matrix', hue: '#a78bfa' };
  switch (emotion) {
    case 'love':
      return { spawnEveryMs: 360, symbol: 'heart', hue: '#fb7185' };
    case 'joyful':
      return { spawnEveryMs: 180, symbol: 'sparkle', hue: '#fde68a' };
    case 'sad':
      return { spawnEveryMs: 700, symbol: 'drop', hue: '#60a5fa' };
    case 'confused':
      return { spawnEveryMs: 900, symbol: 'question', hue: '#fbbf24' };
    default:
      return null;
  }
}

function glowFor(emotion: Emotion, energy: EnergyState): string {
  // colour, intensity baked into a CSS box-shadow (multi-layer for soft halo).
  let hue = 'rgba(16,185,129,0.45)'; // emerald (default)
  if (energy === 'listening') hue = 'rgba(59,130,246,0.55)';     // blue
  else if (energy === 'thinking') hue = 'rgba(167,139,250,0.55)'; // violet
  else if (energy === 'speaking') hue = 'rgba(251,191,36,0.55)';  // gold
  else if (energy === 'sleeping' || energy === 'deep_sleep') hue = 'rgba(30,58,138,0.35)';
  if (emotion === 'love') hue = 'rgba(251,113,133,0.55)';
  else if (emotion === 'joyful') hue = 'rgba(253,224,71,0.55)';
  else if (emotion === 'sad') hue = 'rgba(96,165,250,0.5)';
  else if (emotion === 'error') hue = 'rgba(244,63,94,0.65)';
  return hue;
}

interface ActiveParticle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
  rotation: number;
  symbol: ParticleSpec['symbol'];
  hue: string;
  size: number;
}

export function CaraFaceFX({
  energy = 'idle',
  emotion = 'neutral',
  size = 96,
  className = '',
  particles = true,
  glow = true,
  gestures = false,
  onTap,
  onSwipe,
  onLongPress,
  onLongPressEnd,
}: CaraFaceFXProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const particlesRef = useRef<ActiveParticle[]>([]);
  const animRef = useRef<number | null>(null);
  const lastSpawnRef = useRef<number>(0);
  const stateRef = useRef<{ energy: EnergyState; emotion: Emotion }>({ energy, emotion });

  // Keep state ref synced for the animation loop (closures snapshot)
  useEffect(() => {
    stateRef.current = { energy, emotion };
  }, [energy, emotion]);

  useEffect(() => {
    if (!particles || !canvasRef.current) return;
    const canvas = canvasRef.current;
    canvas.width = size * 2;
    canvas.height = size * 2;
    canvas.style.width = `${size}px`;
    canvas.style.height = `${size}px`;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(2, 2);

    let last = performance.now();

    function frame(now: number) {
      animRef.current = requestAnimationFrame(frame);
      const dt = now - last;
      last = now;

      const spec = particlesFor(stateRef.current.emotion, stateRef.current.energy);
      if (spec && now - lastSpawnRef.current > spec.spawnEveryMs) {
        lastSpawnRef.current = now;
        spawn(spec);
      }

      ctx!.clearRect(0, 0, size, size);

      const next: ActiveParticle[] = [];
      for (const p of particlesRef.current) {
        p.life += dt;
        if (p.life > p.maxLife) continue;
        p.x += p.vx * (dt / 16);
        p.y += p.vy * (dt / 16);
        const t = p.life / p.maxLife;
        const opacity = t < 0.2 ? t / 0.2 : 1 - (t - 0.2) / 0.8;
        drawParticle(ctx!, p, opacity);
        next.push(p);
      }
      particlesRef.current = next;
    }

    function spawn(spec: ParticleSpec) {
      // Spawn at a random point near the face perimeter (rises up).
      const baseX = size * (0.3 + Math.random() * 0.4);
      const startY = size * 0.6;
      particlesRef.current.push({
        x: baseX,
        y: startY,
        vx: (Math.random() - 0.5) * 0.4,
        vy: spec.symbol === 'drop' ? 0.6 : -0.6 - Math.random() * 0.4,
        life: 0,
        maxLife: 1800 + Math.random() * 1000,
        rotation: (Math.random() - 0.5) * 0.6,
        symbol: spec.symbol,
        hue: spec.hue,
        size: 8 + Math.random() * 4,
      });
    }

    animRef.current = requestAnimationFrame(frame);
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
      particlesRef.current = [];
    };
  }, [particles, size]);

  const halo = glowFor(emotion, energy);

  // --- gesture handling: tap / swipe / long-press ---
  const pointerStartRef = useRef<{ x: number; y: number; t: number } | null>(null);
  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPressFiredRef = useRef(false);

  function onPointerDown(e: React.PointerEvent) {
    if (!gestures) return;
    pointerStartRef.current = { x: e.clientX, y: e.clientY, t: performance.now() };
    longPressFiredRef.current = false;
    if (onLongPress) {
      longPressTimerRef.current = setTimeout(() => {
        longPressFiredRef.current = true;
        onLongPress();
      }, 800);
    }
  }

  function onPointerUp(e: React.PointerEvent) {
    if (!gestures) return;
    const start = pointerStartRef.current;
    pointerStartRef.current = null;
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
    if (longPressFiredRef.current) {
      onLongPressEnd?.();
      return;
    }
    if (!start) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    const dist = Math.hypot(dx, dy);
    const dt = performance.now() - start.t;
    if (dist > 30 && Math.abs(dx) > Math.abs(dy)) {
      onSwipe?.(dx > 0 ? 'right' : 'left');
      return;
    }
    if (dist < 12 && dt < 350) {
      onTap?.();
    }
  }

  function onPointerLeave() {
    if (!gestures) return;
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
    pointerStartRef.current = null;
  }

  return (
    <div
      className={`relative inline-block ${className} ${gestures ? 'cursor-pointer select-none' : ''}`}
      style={{
        width: size,
        height: size,
        filter: glow ? `drop-shadow(0 0 ${size * 0.18}px ${halo})` : undefined,
        transition: 'filter 320ms ease',
        touchAction: gestures ? 'none' : undefined,
      }}
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerLeave}
      onPointerCancel={onPointerLeave}
    >
      <CaraFace energy={energy} emotion={emotion} size={size} />
      {particles && (
        <canvas
          ref={canvasRef}
          className="pointer-events-none absolute inset-0"
          aria-hidden="true"
        />
      )}
    </div>
  );
}

function drawParticle(
  ctx: CanvasRenderingContext2D,
  p: ActiveParticle,
  opacity: number,
) {
  ctx.save();
  ctx.globalAlpha = opacity;
  ctx.translate(p.x, p.y);
  ctx.rotate(p.rotation);
  ctx.fillStyle = p.hue;
  ctx.strokeStyle = p.hue;
  ctx.lineWidth = 1.4;
  ctx.font = `${p.size}px system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  switch (p.symbol) {
    case 'heart':
      ctx.fillText('♥', 0, 0);
      break;
    case 'sparkle':
      ctx.fillText('✦', 0, 0);
      break;
    case 'drop':
      ctx.beginPath();
      ctx.moveTo(0, -4);
      ctx.bezierCurveTo(4, 0, 4, 6, 0, 6);
      ctx.bezierCurveTo(-4, 6, -4, 0, 0, -4);
      ctx.fill();
      break;
    case 'matrix':
      ctx.fillText(Math.random() > 0.5 ? '1' : '0', 0, 0);
      break;
    case 'question':
      ctx.fillText('?', 0, 0);
      break;
    case 'zzz':
      ctx.fillText('z', 0, 0);
      break;
  }
  ctx.restore();
}
