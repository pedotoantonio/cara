export type Role = 'system' | 'user' | 'assistant';

export interface Message {
  id?: string;
  role: Role;
  content: string;
  // populated only after the assistant turn finishes
  tokensPerSecond?: number;
  firstTokenSeconds?: number;
  toolResults?: Array<{ ok: boolean; detail: string }>;
  /** True if the answer was rewritten by the self-critique pass. */
  revised?: boolean;
}

export interface Conversation {
  id: string;
  user_id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Array<{
    id: string;
    role: Role;
    content: string;
    created_at: string;
    token_count: number | null;
    latency_ms: number | null;
    first_token_ms: number | null;
  }>;
}
