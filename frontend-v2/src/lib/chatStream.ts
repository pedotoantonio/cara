// SSE parser per /api/v1/chat.
// Il backend emette eventi nel formato standard SSE:
//   event: <type>\n
//   data: <json>\n
//   \n
// Tipi: 'meta', 'token', 'audio_chunk', 'done', 'error', 'revision'.
//
// Usiamo fetch + ReadableStream invece di EventSource perché:
// 1. EventSource non supporta header Authorization (serve Bearer)
// 2. EventSource non supporta POST body
// 3. Maggiore controllo sul cleanup/abort

export type ChatEventType =
  | 'meta'
  | 'token'
  | 'audio_chunk'
  | 'done'
  | 'error'
  | 'revision';

export interface ChatEvent<T = Record<string, unknown>> {
  type: ChatEventType;
  data: T;
}

export interface ChatMetaPayload {
  conversation_id: string;
}

export interface ChatTokenPayload {
  text: string;
  token_id?: number;
}

export interface ChatAudioChunkPayload {
  /** base64 WAV bytes */
  audio: string;
  /** mime type, typically audio/wav */
  mime: string;
  /** sample rate Hz */
  sample_rate?: number;
  /** end-of-turn marker on final chunk */
  final?: boolean;
}

export interface ChatDonePayload {
  tokens?: number;
  first_token_seconds?: number;
  total_seconds?: number;
  finish_reason?: string;
}

export interface ChatErrorPayload {
  detail: string;
}

/**
 * Consume an SSE response and dispatch each event to the provided handler.
 * Throws if the response is not OK (no SSE body).
 *
 * @param signal optional AbortSignal — call abort to stop mid-stream.
 */
export async function consumeChatStream(
  response: Response,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const j = await response.json();
      detail = (j.detail as string) ?? detail;
    } catch {
      /* noop */
    }
    throw new Error(detail);
  }
  if (!response.body) throw new Error('No body on chat response');

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  const onAbort = () => {
    void reader.cancel('aborted');
  };
  signal?.addEventListener('abort', onAbort);

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by blank line (\n\n)
      let sepIdx = buffer.indexOf('\n\n');
      while (sepIdx !== -1) {
        const rawEvent = buffer.slice(0, sepIdx);
        buffer = buffer.slice(sepIdx + 2);
        const parsed = parseSseBlock(rawEvent);
        if (parsed) onEvent(parsed);
        sepIdx = buffer.indexOf('\n\n');
      }
    }
    // Flush remaining buffer
    if (buffer.trim()) {
      const parsed = parseSseBlock(buffer);
      if (parsed) onEvent(parsed);
    }
  } finally {
    signal?.removeEventListener('abort', onAbort);
    try {
      reader.releaseLock();
    } catch {
      /* noop */
    }
  }
}

function parseSseBlock(raw: string): ChatEvent | null {
  let type: string | null = null;
  const dataLines: string[] = [];
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) {
      type = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    } else if (line.startsWith(':')) {
      // Comment / keepalive — ignore
    }
  }
  if (!type) return null;
  const dataStr = dataLines.join('\n');
  let data: Record<string, unknown> = {};
  if (dataStr) {
    try {
      data = JSON.parse(dataStr);
    } catch {
      data = { raw: dataStr };
    }
  }
  return { type: type as ChatEventType, data };
}
