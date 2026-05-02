/**
 * Piper TTS playback (server-rendered).
 *
 * The browser fetches a WAV from `/api/v1/voice/synthesize`, decodes it via
 * Web Audio API, and plays it. We also emit boundary-style "pulse" events
 * along the playback timeline so the avatar lip-sync and the live caption
 * keep working — we don't get real word boundaries from server TTS, so we
 * approximate by spreading N evenly-spaced pulses over the audio duration.
 */

import { authFetch } from '../api/auth';

export interface PiperVoice {
  id: string;
  engine: string;
  display_name: string;
  language: string;
  locale: string;
  gender: string | null;
  quality: string;
  sample_rate: number;
  license: string;
  size_mb: number | null;
  description: string | null;
}

export async function listPiperVoices(): Promise<PiperVoice[]> {
  const r = await authFetch('/api/v1/voice/voices');
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getDefaultVoiceId(): Promise<string> {
  const r = await authFetch('/api/v1/voice/default');
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const j = (await r.json()) as { voice_id: string };
  return j.voice_id;
}

interface SynthesizeArgs {
  text: string;
  voiceId?: string;
  speed?: number;
}

async function fetchWav({ text, voiceId, speed }: SynthesizeArgs): Promise<ArrayBuffer> {
  const r = await authFetch('/api/v1/voice/synthesize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      voice_id: voiceId,
      speed: speed ?? 1.0,
    }),
  });
  if (!r.ok) {
    const detail = await r
      .json()
      .then((j) => j.detail)
      .catch(() => `HTTP ${r.status}`);
    throw new Error(detail);
  }
  return r.arrayBuffer();
}

// ---- Web Audio context (lazy, gesture-resumed) ------------------------

let _ctx: AudioContext | null = null;

function getCtx(): AudioContext {
  if (_ctx) return _ctx;
  const W = window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext };
  const C = W.AudioContext ?? W.webkitAudioContext;
  if (!C) throw new Error('Web Audio API not supported');
  _ctx = new C();
  // Resume on the first user gesture (browsers block audio until then).
  const resume = () => {
    _ctx?.resume().catch(() => undefined);
    window.removeEventListener('pointerdown', resume);
    window.removeEventListener('keydown', resume);
  };
  window.addEventListener('pointerdown', resume, { once: true });
  window.addEventListener('keydown', resume, { once: true });
  return _ctx;
}

// ---- playback control --------------------------------------------------

export interface PiperPlaybackHandle {
  /** Stop playback immediately (cancels remaining audio). */
  stop: () => void;
}

interface PlayOptions {
  text: string;
  voiceId?: string;
  speed?: number;
  volume?: number;
  /** Fired when the OS audio engine actually starts emitting sound. */
  onStart?: () => void;
  /** Fired with the spoken word at each simulated boundary. */
  onPulse?: (word: string) => void;
  /** Fired once playback finishes naturally OR is cancelled. */
  onEnd?: () => void;
  /** Fired if synthesis or playback errored out. */
  onError?: (error: Error) => void;
}

let _activeSource: AudioBufferSourceNode | null = null;
let _activePulseTimers: ReturnType<typeof setTimeout>[] = [];

export function piperStop(): void {
  for (const t of _activePulseTimers) clearTimeout(t);
  _activePulseTimers = [];
  if (_activeSource) {
    try {
      _activeSource.stop();
    } catch {
      // already stopped
    }
    _activeSource.disconnect();
    _activeSource = null;
  }
}

export async function piperSpeak(opts: PlayOptions): Promise<PiperPlaybackHandle> {
  // Cancel anything currently playing.
  piperStop();

  const ctx = getCtx();
  if (ctx.state === 'suspended') {
    try {
      await ctx.resume();
    } catch {
      // ignore — may already be resumed
    }
  }

  let buf: AudioBuffer;
  try {
    const wavBytes = await fetchWav({
      text: opts.text,
      voiceId: opts.voiceId,
      speed: opts.speed,
    });
    // decodeAudioData mutates input ArrayBuffer in some implementations, so clone.
    buf = await ctx.decodeAudioData(wavBytes.slice(0));
  } catch (e) {
    const err = e as Error;
    opts.onError?.(err);
    opts.onEnd?.();
    return { stop: () => undefined };
  }

  const source = ctx.createBufferSource();
  source.buffer = buf;

  const gain = ctx.createGain();
  gain.gain.value = opts.volume ?? 1;

  source.connect(gain).connect(ctx.destination);

  const words = opts.text
    .replace(/\s+/g, ' ')
    .trim()
    .split(' ')
    .filter(Boolean);
  const totalMs = buf.duration * 1000;

  source.onended = () => {
    _activeSource = null;
    for (const t of _activePulseTimers) clearTimeout(t);
    _activePulseTimers = [];
    opts.onEnd?.();
  };

  _activeSource = source;
  source.start();
  opts.onStart?.();

  // Approximate word-boundary pulses by spreading them evenly across the
  // audio duration. Not phonetically accurate, but enough to drive the
  // avatar's lip-sync and the live-caption karaoke cursor.
  if (opts.onPulse && words.length > 0) {
    const stepMs = totalMs / words.length;
    for (let i = 0; i < words.length; i++) {
      const t = setTimeout(() => opts.onPulse?.(words[i]), Math.round(stepMs * i));
      _activePulseTimers.push(t);
    }
  }

  return { stop: () => piperStop() };
}
