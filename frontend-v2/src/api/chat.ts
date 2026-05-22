// Chat + conversations API client.
import { apiGet, apiPost, authFetch } from './client';

export interface Conversation {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  created_at: string;
  tool_calls?: unknown[] | null;
}

export interface ChatRequestPayload {
  messages: Array<{ role: 'user' | 'assistant' | 'system'; content: string }>;
  max_new_tokens?: number;
  temperature?: number;
  file_ids?: string[];
}

export async function listConversations(): Promise<Conversation[]> {
  return apiGet<Conversation[]>('/conversations');
}

export async function getMessages(conversationId: string): Promise<ChatMessage[]> {
  return apiGet<ChatMessage[]>(`/conversations/${conversationId}/messages`);
}

export async function createConversation(title?: string): Promise<Conversation> {
  return apiPost<Conversation>('/conversations', { title: title ?? null });
}

export async function deleteConversation(id: string): Promise<void> {
  const r = await authFetch(`/conversations/${id}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

/**
 * Send a chat turn and get back a `Response` whose body is an SSE stream.
 * Caller is responsible for parsing the stream via `chatStream.ts`.
 * Returns the raw Response; do not consume `.body` here.
 */
export async function streamChat(
  payload: ChatRequestPayload,
  conversationId?: string,
): Promise<Response> {
  const url = conversationId
    ? `/chat?conversation_id=${encodeURIComponent(conversationId)}`
    : '/chat';
  return authFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}
