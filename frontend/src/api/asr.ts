import { authFetch } from './auth';

export interface AsrResult {
  text: string;
  language: string;
  duration_s: number;
  elapsed_ms: number;
}

/** Upload an audio blob to the server-side Whisper transcriber. */
export async function transcribeAudio(blob: Blob, language: string = 'it'): Promise<AsrResult> {
  const fd = new FormData();
  fd.append('audio', blob, 'recording.webm');
  const r = await authFetch(`/api/v1/asr/transcribe?language=${encodeURIComponent(language)}`, {
    method: 'POST',
    body: fd,
  });
  if (!r.ok) {
    const detail = await r.json().then((j) => j.detail).catch(() => `HTTP ${r.status}`);
    throw new Error(detail);
  }
  return r.json();
}
