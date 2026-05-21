/**
 * Server-side Whisper STT — used as a fallback when the browser
 * SpeechRecognition API doesn't produce a transcript.
 *
 * v2 (2026-05-20): now backed by `micPipeline.ts` so callers get a
 * live audio level + VAD auto-stop + structured diagnostics on every
 * session. The legacy `WhisperRecorderHandle` shape is kept for
 * backwards compatibility but new code should use `startMicSession`
 * + `transcribeAudio` directly.
 */

import { transcribeAudio } from '../api/asr';
import {
  diagnoseMicFailure,
  micPipelineAvailable,
  startMicSession,
  type MicPipelineDiagnostics,
  type MicPipelineOptions,
} from './micPipeline';

export interface WhisperRecorderHandle {
  /** Stop the recording AND return the transcript text only.
   *
   *  Returns "" if nothing was recognised. Callers that want
   *  diagnostics should use `stopWithDiag()` instead. */
  stop: () => Promise<string>;
  /** Like stop() but also returns mic-pipeline diagnostics. */
  stopWithDiag: () => Promise<{
    text: string;
    diag: MicPipelineDiagnostics;
    elapsedMs?: number;
    confidence?: string;
    failureHint?: string | null;
  }>;
  /** Stop without uploading (cancel). */
  abort: () => void;
}

export function whisperRecorderAvailable(): boolean {
  return micPipelineAvailable();
}

export async function startWhisperRecording(opts: {
  /** Optional language hint passed to whisper. Defaults to "it". */
  language?: string;
  /** Hard cap on recording duration (ms). Default 30 s. */
  maxDurationMs?: number;
  /**
   * Forwarded to micPipeline — `auto` enables VAD silence stop.
   * Default 'auto' on home page; pass 'manual' for push-to-talk.
   */
  vadMode?: MicPipelineOptions['vadMode'];
  /** Live level callback (dBFS, normalised). */
  onLevel?: MicPipelineOptions['onLevel'];
  /** Fired the first time speech is detected this session. */
  onSpeechStart?: MicPipelineOptions['onSpeechStart'];
  /** Fired when VAD auto-stop triggers. */
  onAutoStop?: MicPipelineOptions['onAutoStop'];
} = {}): Promise<WhisperRecorderHandle> {
  if (!micPipelineAvailable()) {
    throw new Error('MediaRecorder non supportato in questo browser');
  }

  const session = await startMicSession({
    maxDurationMs: opts.maxDurationMs ?? 30_000,
    vadMode: opts.vadMode ?? 'auto',
    onLevel: opts.onLevel,
    onSpeechStart: opts.onSpeechStart,
    onAutoStop: opts.onAutoStop,
  });

  let cachedResult: {
    text: string;
    diag: MicPipelineDiagnostics;
    elapsedMs?: number;
    confidence?: string;
    failureHint?: string | null;
  } | null = null;

  async function _doStop() {
    if (cachedResult) return cachedResult;
    const { blob, diag } = await session.stop();
    // Don't bother uploading <300 ms / <2 KB — that's the user
    // tapping twice quickly with nothing said.
    if (diag.recordedMs < 300 || blob.size < 2000) {
      cachedResult = {
        text: '',
        diag,
        failureHint: diagnoseMicFailure(diag, '', 'empty'),
      };
      _logSession(opts.language ?? 'it', cachedResult);
      return cachedResult;
    }
    const result = await transcribeAudio(blob, opts.language ?? 'it');
    const text = (result.text || '').trim();
    const failureHint = diagnoseMicFailure(
      diag, text, result.confidence_label,
    );
    cachedResult = {
      text,
      diag,
      elapsedMs: result.elapsed_ms,
      confidence: result.confidence_label,
      failureHint,
    };
    _logSession(opts.language ?? 'it', cachedResult);
    return cachedResult;
  }

  return {
    stop: async () => (await _doStop()).text,
    stopWithDiag: _doStop,
    abort: () => session.abort(),
  };
}

function _logSession(language: string, r: {
  text: string;
  diag: MicPipelineDiagnostics;
  elapsedMs?: number;
  confidence?: string;
  failureHint?: string | null;
}) {
  // Single console line per session — easy to copy/paste from a
  // user's browser when troubleshooting "il microfono non funziona".
  // eslint-disable-next-line no-console
  console.info('[cara-mic]', {
    lang: language,
    text_chars: r.text.length,
    text_preview: r.text.slice(0, 40),
    confidence: r.confidence,
    asr_ms: r.elapsedMs,
    failure_hint: r.failureHint,
    ...r.diag,
  });
}
