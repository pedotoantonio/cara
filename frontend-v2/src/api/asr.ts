// ASR (Speech-to-Text) API client.
// Audio → POST /api/v1/asr → Whisper backend → text + sanity.

import { authFetch } from './client';

export interface AsrResult {
  text: string;
  language?: string;
  duration_s?: number;
  avg_logprob?: number | null;
  no_speech_prob?: number | null;
  confidence_label?: 'empty' | 'low' | 'medium' | 'high';
  elapsed_ms?: number;
  sanity?: {
    ok: boolean;
    reason: string | null;
    canned_reply: string | null;
  };
}

export async function transcribeBlob(blob: Blob, language = 'it'): Promise<AsrResult> {
  const fd = new FormData();
  fd.append('audio', blob, blob.type.includes('webm') ? 'rec.webm' : 'rec.audio');
  const r = await authFetch(`/asr?language=${encodeURIComponent(language)}`, {
    method: 'POST',
    body: fd,
  });
  if (!r.ok) {
    throw new Error(`ASR failed: HTTP ${r.status}`);
  }
  return r.json() as Promise<AsrResult>;
}
