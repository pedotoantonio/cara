/**
 * Web Speech API helpers — pure browser-side, no server dependency.
 *
 * TTS: uses the OS-installed voices via `speechSynthesis`. We prefer
 * "Paola" (Italian, premium on Apple devices) and fall back to any it-IT
 * voice; English fallback to en-US/en-GB.
 *
 * STT: uses `SpeechRecognition` (Webkit-prefixed on iOS/Safari). Locale
 * defaults to it-IT; the caller can override.
 *
 * Both APIs are unavailable on some browsers / OSes (notably Firefox for STT,
 * desktop Chrome on Linux for several voices). We expose `available()` so
 * the UI can hide controls cleanly.
 */

const PREFERRED_IT = ['Paola', 'Alice', 'Luca'];

let _voicesCache: SpeechSynthesisVoice[] = [];

function refreshVoices() {
  _voicesCache = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
}

if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
  refreshVoices();
  window.speechSynthesis.onvoiceschanged = refreshVoices;
}

export function ttsAvailable(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

export function listVoices(): SpeechSynthesisVoice[] {
  if (_voicesCache.length === 0) refreshVoices();
  return _voicesCache;
}

// --- voice config (from admin) ---------------------------------------------
//
// The admin panel stores name/rate/pitch/volume in the backend. The frontend
// fetches it once on app start and caches it here. `speak()` reads from this
// cache when the caller doesn't pass an explicit override.

interface VoiceConfig {
  name?: string;
  rate?: number;
  pitch?: number;
  volume?: number;
}

let _voiceConfig: VoiceConfig = {};

export function setVoiceConfig(cfg: {
  name?: string | null;
  rate?: number | null;
  pitch?: number | null;
  volume?: number | null;
}): void {
  _voiceConfig = {
    name: cfg.name?.trim() || undefined,
    rate: cfg.rate ?? undefined,
    pitch: cfg.pitch ?? undefined,
    volume: cfg.volume ?? undefined,
  };
}

export function getVoiceConfig(): Readonly<VoiceConfig> {
  return _voiceConfig;
}

export function pickVoice(
  lang: 'it' | 'en' = 'it',
  preferredName?: string,
): SpeechSynthesisVoice | null {
  const voices = listVoices();
  if (voices.length === 0) return null;
  const wanted = preferredName ?? _voiceConfig.name;
  if (wanted) {
    const v = voices.find((x) => x.name === wanted);
    if (v) return v;
  }
  const target = lang === 'it' ? 'it' : 'en';
  if (target === 'it') {
    for (const name of PREFERRED_IT) {
      const v = voices.find((x) => x.name === name);
      if (v) return v;
    }
    const v = voices.find((x) => x.lang.toLowerCase().startsWith('it'));
    if (v) return v;
  } else {
    const v =
      voices.find((x) => x.lang.toLowerCase() === 'en-gb') ??
      voices.find((x) => x.lang.toLowerCase() === 'en-us') ??
      voices.find((x) => x.lang.toLowerCase().startsWith('en'));
    if (v) return v;
  }
  return voices[0];
}

export interface SpeakOptions {
  lang?: 'it' | 'en';
  rate?: number;        // 0.1–10, default 1
  pitch?: number;       // 0–2, default 1
  volume?: number;      // 0–1, default 1
  /** Override admin-set voice name preference (e.g. for in-admin previews). */
  voiceName?: string;
  onEnd?: () => void;
}

// --- speaking event bus ------------------------------------------------
//
// `speechSynthesis` does not expose audio amplitude, but it fires
// `onboundary` events as each word starts. We use those events to drive a
// "pulse" timeline that downstream UI (avatar) can subscribe to in order
// to animate eyes/brows in sync.

type SpeakEventListener = (event: SpeakEvent) => void;
export type SpeakEvent =
  | { type: 'start' }
  | { type: 'end' }
  | { type: 'pulse'; word: string };

const _listeners = new Set<SpeakEventListener>();

export function onSpeakEvent(fn: SpeakEventListener): () => void {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}

function _emit(ev: SpeakEvent) {
  for (const l of _listeners) l(ev);
}

/**
 * Split a long passage into speech-friendly chunks.
 *
 * Chromium and Safari have a long-standing bug where utterances longer than
 * ~200 chars (or after the first full stop) get truncated silently — the
 * voice says "Ecco le ultime notizie." and falls quiet. The fix is to chop
 * the text into <=180-char pieces broken on sentence boundaries and queue
 * them as separate utterances; `speechSynthesis` plays the queue in order.
 */
function chunkForSpeech(text: string, maxLen = 180): string[] {
  const clean = text.replace(/\s+/g, ' ').trim();
  if (!clean) return [];
  if (clean.length <= maxLen) return [clean];

  // Try sentence-aware split first (full stop / question / exclamation
  // followed by space). Fall back to greedy slicing if a single sentence
  // is too long.
  const sentences = clean.match(/[^.!?]+[.!?]?/g) ?? [clean];
  const out: string[] = [];
  let buf = '';
  for (const raw of sentences) {
    const s = raw.trim();
    if (!s) continue;
    if ((buf + ' ' + s).trim().length <= maxLen) {
      buf = (buf ? buf + ' ' : '') + s;
    } else {
      if (buf) {
        out.push(buf);
        buf = '';
      }
      if (s.length <= maxLen) {
        buf = s;
      } else {
        // single oversized sentence: chop on words
        let i = 0;
        while (i < s.length) {
          const slice = s.slice(i, i + maxLen);
          const lastSpace = slice.lastIndexOf(' ');
          const cut = lastSpace > maxLen * 0.6 ? lastSpace : slice.length;
          out.push(s.slice(i, i + cut).trim());
          i += cut;
        }
      }
    }
  }
  if (buf) out.push(buf);
  return out;
}

export function speak(text: string, opts: SpeakOptions = {}) {
  if (!ttsAvailable() || !text.trim()) return;
  const synth = window.speechSynthesis;
  // Cancel any previous speech to avoid pile-up.
  synth.cancel();

  const v = pickVoice(opts.lang ?? 'it', opts.voiceName);
  const chunks = chunkForSpeech(text);
  if (chunks.length === 0) return;
  const lastIdx = chunks.length - 1;

  // Resolve final knobs: explicit call args > admin config > spec default.
  const rate = opts.rate ?? _voiceConfig.rate ?? 1;
  const pitch = opts.pitch ?? _voiceConfig.pitch ?? 1;
  const volume = opts.volume ?? _voiceConfig.volume ?? 1;

  chunks.forEach((chunk, i) => {
    const utt = new SpeechSynthesisUtterance(chunk);
    if (v) {
      utt.voice = v;
      utt.lang = v.lang;
    }
    utt.rate = rate;
    utt.pitch = pitch;
    utt.volume = volume;
    if (i === 0) utt.onstart = () => _emit({ type: 'start' });
    if (i === lastIdx) {
      utt.onend = () => {
        _emit({ type: 'end' });
        opts.onEnd?.();
      };
    }
    utt.onboundary = (ev: SpeechSynthesisEvent) => {
      if ((ev as { name?: string }).name && (ev as { name?: string }).name !== 'word') return;
      const word = chunk.slice(ev.charIndex, ev.charIndex + (ev.charLength ?? 0));
      _emit({ type: 'pulse', word });
    };
    synth.speak(utt);
  });

  // Chromium has another long-standing bug: after ~15 s the engine pauses
  // its own queue. A periodic resume() while we have utterances queued
  // keeps it going.
  if (chunks.length > 1) {
    const pump = setInterval(() => {
      if (!synth.speaking && !synth.pending) {
        clearInterval(pump);
        return;
      }
      if (synth.paused) synth.resume();
    }, 4000);
  }
}

export function stopSpeaking() {
  if (ttsAvailable()) window.speechSynthesis.cancel();
  _emit({ type: 'end' });
}

export function isSpeaking(): boolean {
  return ttsAvailable() && window.speechSynthesis.speaking;
}

// ---------- STT ----------

type SpeechRecognitionCtor = new () => SpeechRecognitionInstance;

interface SpeechRecognitionInstance {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((ev: { results: { isFinal: boolean; 0: { transcript: string } }[] }) => void) | null;
  onend: (() => void) | null;
  onerror: ((ev: { error: string }) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const w = window as any;
  return (w.SpeechRecognition ?? w.webkitSpeechRecognition) ?? null;
}

export function sttAvailable(): boolean {
  return getRecognitionCtor() !== null;
}

export interface ListenHandle {
  stop: () => void;
}

export interface ListenOptions {
  lang?: 'it' | 'en';
  interim?: boolean;
  onText: (text: string, isFinal: boolean) => void;
  onEnd?: () => void;
  onError?: (error: string) => void;
}

export function startListening(opts: ListenOptions): ListenHandle | null {
  const Ctor = getRecognitionCtor();
  if (!Ctor) return null;
  const rec = new Ctor();
  rec.lang = opts.lang === 'en' ? 'en-US' : 'it-IT';
  rec.interimResults = opts.interim ?? false;
  rec.continuous = false;
  rec.onresult = (ev) => {
    const last = ev.results[ev.results.length - 1];
    const transcript = last[0].transcript;
    opts.onText(transcript, last.isFinal);
  };
  rec.onend = () => opts.onEnd?.();
  rec.onerror = (ev) => opts.onError?.(ev.error);
  try {
    rec.start();
  } catch (e) {
    opts.onError?.((e as Error).message);
    return null;
  }
  return { stop: () => rec.stop() };
}
