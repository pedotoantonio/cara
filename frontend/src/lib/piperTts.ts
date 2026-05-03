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
let _activePulseRaf: number | null = null;

export function piperStop(): void {
  if (_activePulseRaf !== null) {
    cancelAnimationFrame(_activePulseRaf);
    _activePulseRaf = null;
  }
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

  // Word array — keep insertion order, also remember `charIndex` of each word
  // in the original text so the consumer can colour the karaoke cursor.
  const wordsClean = opts.text.replace(/\s+/g, ' ').trim();
  const words: { word: string; charIndex: number }[] = [];
  {
    const re = /\S+/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(wordsClean)) !== null) {
      words.push({ word: m[0], charIndex: m.index });
    }
  }
  const totalSeconds = Math.max(0.001, buf.duration);

  source.onended = () => {
    _activeSource = null;
    if (_activePulseRaf !== null) {
      cancelAnimationFrame(_activePulseRaf);
      _activePulseRaf = null;
    }
    opts.onEnd?.();
  };

  _activeSource = source;
  const startedAt = ctx.currentTime;
  source.start();
  opts.onStart?.();

  // Drive pulse events from the AudioContext clock instead of setTimeout, so
  // the karaoke cursor stays in lock-step with the actual audio playback —
  // even when the browser tab is throttled or the main thread stalls. We
  // poll at the screen refresh rate via requestAnimationFrame and emit the
  // word that the elapsed audio time corresponds to.
  if (opts.onPulse && words.length > 0) {
    let nextIdx = 0;
    const stepSec = totalSeconds / words.length;
    const tick = () => {
      if (_activeSource !== source) return;   // we got cancelled
      const elapsed = ctx.currentTime - startedAt;
      while (nextIdx < words.length && elapsed >= stepSec * nextIdx) {
        opts.onPulse?.(words[nextIdx].word);
        nextIdx++;
      }
      if (nextIdx < words.length) {
        _activePulseRaf = requestAnimationFrame(tick);
      } else {
        _activePulseRaf = null;
      }
    };
    _activePulseRaf = requestAnimationFrame(tick);
  }

  return { stop: () => piperStop() };
}
