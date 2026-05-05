import { authFetch, authHeaders, clearTokens, getRefreshToken } from './auth';
import type { Conversation, ConversationDetail, Message } from '../types/chat';

const API = '/api/v1';

export async function listConversations(): Promise<Conversation[]> {
  const r = await authFetch(`${API}/conversations`);
  if (!r.ok) throw new Error(`list failed: ${r.status}`);
  return r.json();
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const r = await authFetch(`${API}/conversations/${id}`);
  if (!r.ok) throw new Error(`get failed: ${r.status}`);
  return r.json();
}

export async function deleteConversation(id: string): Promise<void> {
  const r = await authFetch(`${API}/conversations/${id}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`delete failed: ${r.status}`);
}

export interface ChatAudioChunk {
  seq: number;
  text: string;
  voice_id: string;
  format: string;
  audio_b64: string;
  bytes: number;
}

export interface ChatStreamHandlers {
  onMeta: (conversationId: string) => void;
  onToken: (text: string) => void;
  /** Server replaced the previous reply with a validated rewrite. */
  onRevision?: (text: string) => void;
  /** Sentence-streamed TTS chunk (base64 WAV). Optional handler — when
   *  absent the audio_chunk events are simply ignored and the caller
   *  is expected to call `speak()` on done as before. */
  onAudioChunk?: (chunk: ChatAudioChunk) => void;
  onDone: (stats: { tokens: number; tokensPerSecond: number; firstTokenSeconds: number }) => void;
  onError: (detail: string) => void;
}

/**
 * Stream tokens from POST /api/v1/chat over SSE.
 * Returns a function that aborts the in-flight request.
 */
export function streamChat(
  args: {
    messages: Message[];
    conversationId?: string;
    maxNewTokens?: number;
    fileIds?: string[];
    /** When true AND the admin flag `cloud_llm_enabled` is on, this
     *  single turn is routed to Anthropic Haiku instead of the local
     *  1.5B. Privacy: only the last user message is sent. */
    preferCloud?: boolean;
  },
  h: ChatStreamHandlers,
): () => void {
  const controller = new AbortController();
  const url = args.conversationId
    ? `${API}/chat?conversation_id=${args.conversationId}`
    : `${API}/chat`;

  const body = JSON.stringify({
    messages: args.messages.map((m) => ({ role: m.role, content: m.content })),
    max_new_tokens: args.maxNewTokens ?? 512,
    file_ids: args.fileIds ?? [],
    prefer_cloud: args.preferCloud ?? false,
  });

  const doPost = (): Promise<Response> =>
    fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...authHeaders(),
      },
      body,
      signal: controller.signal,
    });

  (async () => {
    let resp: Response;
    try {
      resp = await doPost();
      // If access token expired, try one refresh+retry (authFetch can't be used
      // for streaming POST because we need direct access to the response body).
      if (resp.status === 401) {
        const r = getRefreshToken();
        if (r) {
          const rr = await fetch(`${API}/auth/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: r }),
          });
          if (rr.ok) {
            const data = await rr.json();
            localStorage.setItem('cara.access_token', data.access_token);
            localStorage.setItem('cara.refresh_token', data.refresh_token);
            resp = await doPost();
          } else {
            clearTokens();
          }
        }
      }
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      h.onError((e as Error).message);
      return;
    }

    if (!resp.ok || !resp.body) {
      h.onError(`HTTP ${resp.status}`);
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch (e) {
        if ((e as Error).name === 'AbortError') return;
        h.onError((e as Error).message);
        return;
      }
      if (chunk.done) break;
      buf += decoder.decode(chunk.value, { stream: true });

      // Parse SSE: events are separated by blank lines
      let idx;
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let event = 'message';
        let data = '';
        for (const line of raw.split('\n')) {
          if (line.startsWith('event: ')) event = line.slice(7).trim();
          else if (line.startsWith('data: ')) data += line.slice(6);
        }
        if (!data) continue;
        try {
          const payload = JSON.parse(data);
          if (event === 'meta') h.onMeta(payload.conversation_id);
          else if (event === 'token') h.onToken(payload.text ?? '');
          else if (event === 'revision') h.onRevision?.(payload.text ?? '');
          else if (event === 'audio_chunk') h.onAudioChunk?.(payload as ChatAudioChunk);
          else if (event === 'done')
            h.onDone({
              tokens: payload.tokens ?? 0,
              tokensPerSecond: payload.tokens_per_second ?? 0,
              firstTokenSeconds: payload.first_token_seconds ?? 0,
            });
          else if (event === 'error') h.onError(payload.detail ?? 'unknown');
        } catch {
          // ignore malformed event
        }
      }
    }
  })();

  return () => controller.abort();
}
