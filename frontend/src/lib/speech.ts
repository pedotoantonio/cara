/**
 * Speech helpers — both browser-side TTS and the server-rendered Piper TTS.
 *
 * TTS engines:
 *   - **browser**: `SpeechSynthesisUtterance` (OS-installed voices). On iPhone
 *     this is premium "Paola"; on Linux/Chrome desktop it's eSpeak robotic.
 *   - **piper**: `/api/v1/voice/synthesize` returns WAV from server-side Piper.
 *     Same quality on every device; ~1 s of network round-trip + decode.
 *
 * `speak()` routes to whichever engine the user picked in their localStorage
 * preferences. Both emit the same `onSpeakEvent` bus (`start`, `pulse(word)`,
 * `end`) so downstream consumers (avatar lip-sync, live caption) work
 * regardless of engine.
 *
 * STT: uses `SpeechRecognition` (Webkit-prefixed on iOS/Safari). Locale
 * defaults to it-IT; the caller can override.
 *
 * Both APIs are unavailable on some browsers / OSes (notably Firefox for STT,
 * desktop Chrome on Linux for several voices). We expose `available()` so
 * the UI can hide controls cleanly.
 */

import { setAiPhase } from './aiState';
import { piperSpeak, piperStop } from './piperTts';
import { loadPrefs } from './userPrefs';

const PREFERRED_IT = ['Paola', 'Alice', 'Luca'];

let _voicesCache: SpeechSynthesisVoice[] = [];

function refreshVoices() {
  _voicesCache = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
}

if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
  refreshVoices();
  window.speechSynthesis.onvoiceschanged = refreshVoices;
}

/** True if the device can synthesise speech in any way (browser or Piper).
 * Server-side Piper works on every modern browser via fetch + Web Audio. */
export function ttsAvailable(): boolean {
  if (typeof window === 'undefined') return false;
  if ('speechSynthesis' in window) return true;
  // Piper still works as long as we can fetch and play audio.
  const w = window as unknown as { fetch?: unknown; AudioContext?: unknown; webkitAudioContext?: unknown };
  return typeof w.fetch === 'function' && (Boolean(w.AudioContext) || Boolean(w.webkitAudioContext));
}

/** True only if the browser exposes SpeechSynthesisUtterance (used by the
 * "voce del browser" engine). The settings UI reads this to know whether
 * to offer the toggle at all. */
export function browserTtsAvailable(): boolean {
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
  // Mirror to the global AI state so the ambient banner reflects TTS
  // activity from any caller — including the text chat page that doesn't
  // own a useVoiceConversation hook.
  if (ev.type === 'start') setAiPhase('speaking');
  else if (ev.type === 'end') setAiPhase('idle');
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
  if (!text.trim()) return;
  // Resolve final knobs: explicit call args > admin config > spec default.
  const rate = opts.rate ?? _voiceConfig.rate ?? 1;
  const pitch = opts.pitch ?? _voiceConfig.pitch ?? 1;
  const volume = opts.volume ?? _voiceConfig.volume ?? 1;

  // Engine routing: user's per-device preference picks browser vs Piper.
  // If the user is on a browser with no SpeechSynthesis (e.g. Firefox on
  // Linux), we fall back to Piper transparently. If Piper is unreachable,
  // its own onError fires and we surface end so the caller's logic resumes.
  const prefs = loadPrefs();
  const engine: 'piper' | 'browser' = (() => {
    if (prefs.ttsEngine === 'piper') return 'piper';
    if (prefs.ttsEngine === 'browser' && ttsAvailable()) return 'browser';
    // browser preferred but unavailable → piper
    return 'piper';
  })();

  if (engine === 'piper') {
    // Stop any browser TTS in flight before switching engines.
    if (ttsAvailable() && 'speechSynthesis' in window) window.speechSynthesis.cancel();
    // If admin set voice_name as "piper:..." use it; else server picks default.
    const adminName = _voiceConfig.name;
    const piperVoiceId = adminName?.startsWith('piper:') ? adminName : undefined;
    void piperSpeak({
      text,
      voiceId: opts.voiceName?.startsWith('piper:') ? opts.voiceName : piperVoiceId,
      speed: rate,
      volume,
      onStart: () => _emit({ type: 'start' }),
      onPulse: (word) => _emit({ type: 'pulse', word }),
      onEnd: () => {
        _emit({ type: 'end' });
        opts.onEnd?.();
      },
      onError: () => undefined,
    });
    return;
  }

  if (!ttsAvailable()) return;
  const synth = window.speechSynthesis;
  // Cancel any previous speech to avoid pile-up.
  synth.cancel();

  const v = pickVoice(opts.lang ?? 'it', opts.voiceName);
  const chunks = chunkForSpeech(text);
  if (chunks.length === 0) return;
  const lastIdx = chunks.length - 1;

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
  piperStop();
  _emit({ type: 'end' });
}

export function isSpeaking(): boolean {
  return ttsAvailable() && window.speechSynthesis.speaking;
}

// ---------- STT ----------

type SpeechRecognitionCtor = new () => SpeechRecognitionInstance;

interface SpeechRecognitionAlternative {
  transcript: string;
  confidence?: number;
}

interface SpeechRecognitionResult {
  isFinal: boolean;
  length: number;
  0: SpeechRecognitionAlternative;
  [k: number]: SpeechRecognitionAlternative;
}

interface SpeechRecognitionInstance {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives?: number;
  onresult:
    | ((ev: { results: SpeechRecognitionResult[]; resultIndex?: number }) => void)
    | null;
  onend: (() => void) | null;
  onerror: ((ev: { error: string }) => void) | null;
  onstart?: (() => void) | null;
  onaudiostart?: (() => void) | null;
  onaudioend?: (() => void) | null;
  onspeechstart?: (() => void) | null;
  onspeechend?: (() => void) | null;
  onnomatch?: (() => void) | null;
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
  abort: () => void;
}

export interface ListenOptions {
  lang?: 'it' | 'en';
  interim?: boolean;
  /** Default: true for conversational STT (the recognizer doesn't quit at the
   * first natural pause). Wake-word callers pass false. */
  continuous?: boolean;
  onText: (text: string, isFinal: boolean) => void;
  onEnd?: () => void;
  onError?: (error: string) => void;
}

function logStt(...args: unknown[]) {
  // eslint-disable-next-line no-console
  console.log('[cara-stt]', ...args);
}

export function startListening(opts: ListenOptions): ListenHandle | null {
  const Ctor = getRecognitionCtor();
  if (!Ctor) return null;
  const rec = new Ctor();
  rec.lang = opts.lang === 'en' ? 'en-US' : 'it-IT';
  rec.interimResults = opts.interim ?? false;
  // iOS Safari silently refuses to emit results when continuous=true, so
  // the safer default is false. Callers that REALLY want continuous (e.g.
  // wake-word on Chrome) opt in explicitly. For conversational STT we now
  // rely on interim transcripts + a tap-to-submit fallback.
  rec.continuous = opts.continuous ?? false;
  // Ask for up to 3 alternatives — Chrome exposes a `confidence` for each
  // and we pick the highest-confidence one. Safari ignores the field but
  // doesn't error on it.
  rec.maxAlternatives = 3;
  rec.onresult = (ev) => {
    const list = ev.results;
    const len = list.length;
    let combined = '';
    let allFinal = true;
    let bestConfidence = 0;
    for (let i = 0; i < len; i++) {
      const r = list[i];
      // Pick the best alternative for THIS result chunk: prefer the one
      // with the highest confidence; fall back to the first if no
      // confidence is provided (Safari) or all are zero.
      const altCount = (r as SpeechRecognitionResult).length || 1;
      let bestAlt: SpeechRecognitionAlternative = r[0];
      let bestAltConf = bestAlt.confidence ?? 0;
      for (let j = 1; j < altCount; j++) {
        const alt = r[j];
        const c = alt?.confidence ?? 0;
        if (c > bestAltConf) {
          bestAlt = alt;
          bestAltConf = c;
        }
      }
      combined += bestAlt.transcript;
      bestConfidence = Math.max(bestConfidence, bestAltConf);
      if (!r.isFinal) allFinal = false;
    }
    logStt('onresult', {
      transcript: combined,
      allFinal,
      confidence: bestConfidence,
      resultIndex: ev.resultIndex,
    });
    opts.onText(combined.trim(), allFinal);
  };
  rec.onend = () => {
    logStt('onend');
    opts.onEnd?.();
  };
  rec.onerror = (ev) => {
    logStt('onerror', ev.error);
    opts.onError?.(ev.error);
  };
  rec.onstart = () => logStt('onstart');
  rec.onaudiostart = () => logStt('onaudiostart');
  rec.onaudioend = () => logStt('onaudioend');
  rec.onspeechstart = () => logStt('onspeechstart');
  rec.onspeechend = () => logStt('onspeechend');
  rec.onnomatch = () => logStt('onnomatch');
  try {
    rec.start();
    logStt('start() called', { lang: rec.lang, continuous: rec.continuous, interim: rec.interimResults });
  } catch (e) {
    logStt('start() threw', e);
    opts.onError?.((e as Error).message);
    return null;
  }
  return {
    stop: () => {
      try {
        rec.stop();
      } catch {
        /* already stopped */
      }
    },
    abort: () => {
      try {
        rec.abort();
      } catch {
        /* already aborted */
      }
    },
  };
}
