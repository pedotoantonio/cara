import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { List, Plus, X, Trash } from '@phosphor-icons/react';
import { useAvatarStore } from '@/state/avatar';
import { useAuthStore } from '@/state/auth';
import { Sheet, Button, Card, CardSubtitle, useToast } from '@/design/components';
import { MessageBubble } from '@/components/chat/MessageBubble';
import { ChatInput } from '@/components/chat/ChatInput';
import { WelcomeScreen } from '@/components/chat/WelcomeScreen';
import { VoicePanel } from '@/components/voice/VoicePanel';
import {
  createConversation,
  deleteConversation,
  getMessages,
  listConversations,
  streamChat,
  type ChatMessage,
  type Conversation,
} from '@/api/chat';
import {
  consumeChatStream,
  type ChatAudioChunkPayload,
  type ChatTokenPayload,
  type ChatMetaPayload,
} from '@/lib/chatStream';
import { createTtsPlayer } from '@/lib/ttsPlayback';

interface LocalAssistantStream {
  text: string;
  done: boolean;
  speaking: boolean;
}

export function ChatPage() {
  const params = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  const user = useAuthStore((s) => s.user);
  const toast = useToast();
  const queryClient = useQueryClient();

  const [listOpen, setListOpen] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [draftAssistant, setDraftAssistant] = useState<LocalAssistantStream | null>(null);
  const [sending, setSending] = useState(false);

  const ttsPlayerRef = useRef(createTtsPlayer());
  const abortRef = useRef<AbortController | null>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);

  const conversationId = params.conversationId ?? null;

  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: sending ? 'thinking' : 'idle',
      emotion: 'neutral',
      glowAccent: 'lilac',
      caption: null,
      context: 'chat',
    });
  }, [setAvatar, sending]);

  const convosQ = useQuery({
    queryKey: ['conversations'],
    queryFn: listConversations,
    staleTime: 60_000,
  });

  const deleteConvM = useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    onSuccess: (_, id) => {
      queryClient.setQueryData<Conversation[]>(['conversations'], (prev) =>
        prev ? prev.filter((c) => c.id !== id) : prev,
      );
      if (id === conversationId) {
        navigate('/chat', { replace: true });
      }
      toast.push({ tone: 'mint', title: 'Conversazione eliminata' });
    },
    onError: (err) => toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message }),
  });

  const messagesQ = useQuery({
    queryKey: ['conversation.messages', conversationId],
    queryFn: () => (conversationId ? getMessages(conversationId) : Promise.resolve([])),
    enabled: !!conversationId,
    staleTime: 0,
  });

  const messages: ChatMessage[] = useMemo(() => messagesQ.data ?? [], [messagesQ.data]);

  // Auto-scroll to bottom when messages or stream change
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, draftAssistant]);

  async function sendText(text: string) {
    if (sending) return;
    setSending(true);

    // 1. Make sure we have a conversation_id (create on the fly if needed).
    let convId = conversationId;
    if (!convId) {
      try {
        const created = await createConversation();
        convId = created.id;
        // Don't navigate yet — backend chat endpoint will accept the id
        // and we'll navigate after the meta event so the URL changes only
        // on success.
      } catch (err) {
        toast.push({ tone: 'coral', title: 'Impossibile creare conversazione', body: (err as Error).message });
        setSending(false);
        return;
      }
    }

    // 2. Inject the user message optimistically.
    const userMsg: ChatMessage = {
      id: `local-${Date.now()}`,
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    };
    queryClient.setQueryData(['conversation.messages', convId], (prev: ChatMessage[] | undefined) =>
      prev ? [...prev, userMsg] : [userMsg],
    );
    setDraftAssistant({ text: '', done: false, speaking: false });

    // 3. Stream
    abortRef.current = new AbortController();
    setAvatar({ energy: 'thinking', emotion: 'thoughtful', caption: 'Sto pensando…', glowAccent: 'lilac' });

    let assistantText = '';
    let speakingNow = false;

    try {
      const response = await streamChat(
        { messages: [{ role: 'user', content: text }], max_new_tokens: 600 },
        convId,
      );

      await consumeChatStream(
        response,
        (ev) => {
          if (ev.type === 'meta') {
            const meta = ev.data as unknown as ChatMetaPayload;
            if (meta.conversation_id && !conversationId) {
              // Update URL silently to include conv id
              navigate(`/chat/${meta.conversation_id}`, { replace: true });
            }
          } else if (ev.type === 'token') {
            const tok = ev.data as unknown as ChatTokenPayload;
            assistantText += tok.text ?? '';
            setDraftAssistant({ text: assistantText, done: false, speaking: speakingNow });
          } else if (ev.type === 'audio_chunk') {
            const chunk = ev.data as unknown as ChatAudioChunkPayload;
            speakingNow = true;
            setAvatar({ energy: 'speaking', emotion: 'happy' });
            ttsPlayerRef.current.enqueue(chunk);
          } else if (ev.type === 'done') {
            setDraftAssistant({ text: assistantText, done: true, speaking: speakingNow });
          } else if (ev.type === 'error') {
            throw new Error((ev.data as { detail?: string }).detail ?? 'Errore chat');
          }
        },
        abortRef.current.signal,
      );

      // Promote draft to real message + invalidate
      const finalMsg: ChatMessage = {
        id: `local-asst-${Date.now()}`,
        role: 'assistant',
        content: assistantText,
        created_at: new Date().toISOString(),
      };
      queryClient.setQueryData(['conversation.messages', convId], (prev: ChatMessage[] | undefined) =>
        prev ? [...prev, finalMsg] : [finalMsg],
      );
      setDraftAssistant(null);

      // Refresh server-side state in background
      void queryClient.invalidateQueries({ queryKey: ['conversation.messages', convId] });
      void queryClient.invalidateQueries({ queryKey: ['conversations'] });
    } catch (err) {
      toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message });
      setDraftAssistant(null);
    } finally {
      setSending(false);
      setAvatar({ energy: 'idle', emotion: 'neutral', caption: null, glowAccent: 'lilac' });
    }
  }

  function cancelStream() {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    ttsPlayerRef.current.stop();
    setSending(false);
    setDraftAssistant(null);
  }

  async function newConversation() {
    cancelStream();
    setListOpen(false);
    navigate('/chat', { replace: false });
  }

  const empty = messages.length === 0 && !draftAssistant && !sending;

  return (
    <div className="flex flex-col h-[calc(100dvh-4.5rem-env(safe-area-inset-bottom,0))] lg:h-[100dvh]">
      {/* Topbar */}
      <header className="topbar border-b border-border-soft">
        <button
          onClick={() => setListOpen(true)}
          className="p-2 -m-2 rounded-md text-text-secondary hover:bg-bg-surface"
          aria-label="Conversazioni"
        >
          <List size={22} />
        </button>
        <h1 className="text-md font-semibold text-text-primary">Chat con CARA</h1>
        <button
          onClick={newConversation}
          className="p-2 -m-2 rounded-md text-text-secondary hover:bg-bg-surface"
          aria-label="Nuova conversazione"
        >
          <Plus size={22} />
        </button>
      </header>

      {/* Messages */}
      <div ref={scrollerRef} className="flex-1 overflow-y-auto">
        {empty ? (
          <WelcomeScreen userName={user?.full_name ?? undefined} onSuggestion={sendText} />
        ) : (
          <div className="container-app py-4">
            {messages.map((m) =>
              m.role === 'user' || m.role === 'assistant' ? (
                <MessageBubble key={m.id} role={m.role} content={m.content} />
              ) : null,
            )}
            {draftAssistant && (
              <MessageBubble
                role="assistant"
                content={draftAssistant.text}
                streaming={!draftAssistant.done}
                speaking={draftAssistant.speaking}
              />
            )}
          </div>
        )}
      </div>

      {/* Input */}
      <ChatInput onSend={sendText} onVoiceTap={() => setVoiceOpen(true)} disabled={sending} />

      {/* Voice panel */}
      <VoicePanel open={voiceOpen} onClose={() => setVoiceOpen(false)} />

      {/* Conversations list */}
      <Sheet open={listOpen} onClose={() => setListOpen(false)} title="Conversazioni" side="right">
        <Button
          fullWidth
          leftIcon={<Plus size={18} />}
          onClick={newConversation}
          className="mb-3"
        >
          Nuova conversazione
        </Button>
        {convosQ.isLoading && <p className="text-sm text-text-muted">Carico…</p>}
        {convosQ.data && convosQ.data.length === 0 && (
          <p className="text-sm text-text-muted">Nessuna conversazione ancora.</p>
        )}
        <ul className="space-y-2 mt-2">
          {convosQ.data?.map((c: Conversation) => (
            <li key={c.id}>
              <Card
                padding="base"
                elevation={c.id === conversationId ? 2 : 0}
                className={c.id === conversationId ? 'border-accent-lilac/40' : ''}
              >
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => {
                      navigate(`/chat/${c.id}`);
                      setListOpen(false);
                    }}
                    className="flex-1 text-left min-w-0"
                  >
                    <p className="font-medium text-sm truncate">{c.title ?? 'Senza titolo'}</p>
                    <CardSubtitle>
                      {new Date(c.updated_at).toLocaleString('it-IT', {
                        day: '2-digit',
                        month: 'short',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </CardSubtitle>
                  </button>
                  <button
                    onClick={() => {
                      if (window.confirm('Eliminare questa conversazione?')) {
                        deleteConvM.mutate(c.id);
                      }
                    }}
                    aria-label="Elimina conversazione"
                    className="p-2 text-text-muted hover:text-accent-coral rounded-md flex-shrink-0"
                  >
                    <Trash size={16} />
                  </button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      </Sheet>

      {sending && (
        <button
          onClick={cancelStream}
          className="fixed bottom-24 left-1/2 -translate-x-1/2 z-30 inline-flex items-center gap-2 px-4 py-2 rounded-pill bg-text-primary text-text-inverse text-sm shadow-2"
        >
          <X size={14} /> Annulla
        </button>
      )}
    </div>
  );
}
