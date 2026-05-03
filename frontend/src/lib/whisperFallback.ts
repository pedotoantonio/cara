/**
 * Server-side Whisper STT — used as a fallback when the browser
 * SpeechRecognition API doesn't produce a transcript.
 *
 * Records the user's mic via `MediaRecorder`, uploads the blob to the
 * backend, and returns the recognised text.
 */

import { transcribeAudio } from '../api/asr';

export interface WhisperRecorderHandle {
  /** Stop the recording AND return the transcript. */
  stop: () => Promise<string>;
  /** Stop without uploading (cancel). */
  abort: () => void;
}

export function whisperRecorderAvailable(): boolean {
  if (typeof window === 'undefined') return false;
  if (!('MediaRecorder' in window)) return false;
  if (!navigator.mediaDevices?.getUserMedia) return false;
  return true;
}

/**
 * Start recording from the default mic. The recorder runs until `stop()`
 * is called. Returns a handle whose `stop()` uploads the WebM blob to the
 * backend's `/api/v1/asr/transcribe` and resolves with the transcript.
 *
 * Throws if the user denies the microphone permission or if the browser
 * lacks `MediaRecorder` support.
 */
export async function startWhisperRecording(opts: {
  /** Optional language hint passed to whisper. Defaults to "it". */
  language?: string;
  /** Hard cap on recording duration (ms). Default 30 s. */
  maxDurationMs?: number;
} = {}): Promise<WhisperRecorderHandle> {
  if (!whisperRecorderAvailable()) {
    throw new Error('MediaRecorder non supportato in questo browser');
  }

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true },
  });

  // Pick a MIME type the browser actually supports. Order: opus (preferred)
  // then any audio/webm, then the browser default.
  const mimeCandidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', ''];
  let mimeType: string = '';
  for (const m of mimeCandidates) {
    if (m === '' || (window.MediaRecorder?.isTypeSupported?.(m) ?? false)) {
      mimeType = m;
      break;
    }
  }
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  const chunks: BlobPart[] = [];
  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };

  recorder.start();
  const startedAt = performance.now();

  // Hard cap so a forgotten recording doesn't run forever.
  const cap = opts.maxDurationMs ?? 30_000;
  const capTimer = window.setTimeout(() => {
    if (recorder.state === 'recording') recorder.stop();
  }, cap);

  function cleanup() {
    window.clearTimeout(capTimer);
    for (const t of stream.getTracks()) t.stop();
  }

  return {
    stop: async (): Promise<string> => {
      const finished = new Promise<Blob>((resolve, reject) => {
        recorder.onstop = () => {
          try {
            const blob = new Blob(chunks, { type: mimeType || 'audio/webm' });
            resolve(blob);
          } catch (e) {
            reject(e as Error);
          }
        };
        recorder.onerror = (e) => reject(new Error(`MediaRecorder error: ${e}`));
      });
      if (recorder.state === 'recording') recorder.stop();
      cleanup();
      const elapsedMs = performance.now() - startedAt;
      const blob = await finished;
      // Don't bother uploading <300 ms recordings — that's the user
      // tapping twice quickly with nothing said.
      if (elapsedMs < 300 || blob.size < 2000) return '';
      const result = await transcribeAudio(blob, opts.language ?? 'it');
      return (result.text || '').trim();
    },
    abort: () => {
      if (recorder.state === 'recording') recorder.stop();
      chunks.length = 0;
      cleanup();
    },
  };
}
