/**
 * Synth sound pack — micro-suoni di feedback generati al volo via Web Audio
 * (nessun asset binario necessario). Coerenti con il "mondo Casa" del brief
 * volto vivo: morbidi, sinusoidali, brevi (50-300ms).
 *
 * `playSound(name)` è una no-op se l'utente non ha ancora interagito con la
 * pagina (browser blocca AudioContext fino al primo gesture); riprova al
 * prossimo click. Volume globale + on/off via `setSoundsEnabled()`.
 */

export type SoundName =
  | 'notify'
  | 'confirm'
  | 'error'
  | 'celebrate'
  | 'wake'
  | 'tick';

let _ctx: AudioContext | null = null;
let _enabled = true;
let _volume = 0.4;

function ctx(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  if (_ctx) return _ctx;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const Ctor: typeof AudioContext = (window.AudioContext ?? (window as any).webkitAudioContext);
  if (!Ctor) return null;
  try {
    _ctx = new Ctor();
  } catch {
    return null;
  }
  return _ctx;
}

export function setSoundsEnabled(on: boolean) {
  _enabled = on;
}
export function setVolume(v: number) {
  _volume = Math.max(0, Math.min(1, v));
}

interface ToneSpec {
  freq: number;
  duration: number;        // seconds
  delay?: number;          // start offset
  type?: OscillatorType;
  attack?: number;
  release?: number;
  peak?: number;           // 0..1, scaled by global volume
}

function playTones(tones: ToneSpec[]) {
  if (!_enabled) return;
  const c = ctx();
  if (!c) return;
  if (c.state === 'suspended') {
    // Resume on user gesture; browsers mute AudioContext until interaction.
    c.resume().catch(() => undefined);
  }
  const t0 = c.currentTime + 0.005;
  for (const t of tones) {
    const start = t0 + (t.delay ?? 0);
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = t.type ?? 'sine';
    osc.frequency.value = t.freq;
    const peak = (t.peak ?? 1) * _volume;
    const attack = t.attack ?? 0.005;
    const release = t.release ?? 0.06;
    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(peak, start + attack);
    gain.gain.linearRampToValueAtTime(0, start + t.duration + release);
    osc.connect(gain).connect(c.destination);
    osc.start(start);
    osc.stop(start + t.duration + release + 0.02);
  }
}

const PACK: Record<SoundName, ToneSpec[]> = {
  notify: [
    { freq: 880, duration: 0.08, peak: 0.5 },
    { freq: 1320, duration: 0.10, delay: 0.07, peak: 0.45 },
  ],
  confirm: [
    { freq: 660, duration: 0.06, peak: 0.45 },
    { freq: 880, duration: 0.10, delay: 0.05, peak: 0.5 },
  ],
  error: [
    { freq: 320, duration: 0.10, peak: 0.45, type: 'triangle' },
    { freq: 220, duration: 0.18, delay: 0.08, peak: 0.5, type: 'triangle' },
  ],
  celebrate: [
    { freq: 660, duration: 0.08, peak: 0.45 },
    { freq: 880, duration: 0.08, delay: 0.07, peak: 0.5 },
    { freq: 1175, duration: 0.10, delay: 0.14, peak: 0.55 },
    { freq: 1568, duration: 0.20, delay: 0.21, peak: 0.5 },
  ],
  wake: [
    { freq: 523, duration: 0.16, peak: 0.4, type: 'sine' },
  ],
  tick: [
    { freq: 1200, duration: 0.02, peak: 0.18, attack: 0.001, release: 0.005 },
  ],
};

export function playSound(name: SoundName) {
  const spec = PACK[name];
  if (!spec) return;
  playTones(spec);
}
