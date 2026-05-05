import { useEffect, useRef, useState } from 'react';

import type { User } from '../api/auth';
import {
  deleteConversation,
  getConversation,
  listConversations,
  streamChat,
} from '../api/chat';
import { loadPrefs, savePrefs } from '../lib/userPrefs';
import {
  isSpeaking,
  speak,
  startListening,
  stopSpeaking,
  sttAvailable,
  ttsAvailable,
  type ListenHandle,
} from '../lib/speech';
import { useCdaPlayer } from '../lib/cdaPlayer';
import { useRadioPlayer } from '../lib/radioPlayer';
import { ensureSomeProse, executeTools, parseToolCalls } from '../lib/tools';
import type { Conversation, Message } from '../types/chat';
import { Badge, Icon, IconButton, cn } from '../design';
import {
  WorkflowRunResponse,
  fileToBase64,
  runWorkflow,
} from '../api/workflows';
import { CaraFaceFX } from './CaraFaceFX';
import { MessageBubble } from './MessageBubble';
import { WelcomeScreen } from './WelcomeScreen';
import { WorkflowPreview } from './WorkflowPreview';

interface ChatProps {
  user: User;
}

function chatFaceFXState(
  streaming: boolean,
  messages: Message[],
): { energy: 'idle' | 'thinking' | 'speaking'; emotion: 'neutral' | 'thoughtful' } {
  if (!streaming) return { energy: 'idle', emotion: 'neutral' };
  const last = messages[messages.length - 1];
  if (last?.role === 'assistant' && last.content.length > 0) {
    return { energy: 'speaking', emotion: 'neutral' };
  }
  return { energy: 'thinking', emotion: 'thoughtful' };
}

export function Chat({ user }: ChatProps) {
  const [convos, setConvos] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(() => loadPrefs().voiceEnabled);
  const [listening, setListening] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const radioPlayer = useRadioPlayer();
  const cdaPlayer = useCdaPlayer();
  const [pendingFiles, setPendingFiles] = useState<{
    id: string; filename: string; kind: string; raw?: File;
  }[]>([]);
  const [workflowResult, setWorkflowResult] = useState<{
    response: WorkflowRunResponse;
    rerunArgs: { image_b64?: string; pdf_b64?: string; text?: string };
  } | null>(null);
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const abortRef = useRef<(() => void) | null>(null);
  const listenRef = useRef<ListenHandle | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const ttsOk = ttsAvailable();
  const sttOk = sttAvailable();

  useEffect(() => {
    const cur = loadPrefs();
    savePrefs({ ...cur, voiceEnabled });
  }, [voiceEnabled]);

  useEffect(() => () => stopSpeaking(), []);

  useEffect(() => {
    listConversations().then(setConvos).catch(console.error);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function selectConvo(id: string) {
    if (streaming) return;
    setActiveId(id);
    try {
      const detail = await getConversation(id);
      setMessages(
        detail.messages.map((m) => {
          if (m.role === 'assistant') {
            const parsed = parseToolCalls(m.content);
            return {
              id: m.id,
              role: m.role,
              content: ensureSomeProse(parsed.cleaned, parsed.toolCalls) || m.content,
            };
          }
          return { id: m.id, role: m.role, content: m.content };
        }),
      );
    } catch (e) {
      console.error(e);
    }
  }

  function newConversation() {
    if (streaming) return;
    setActiveId(null);
    setMessages([]);
  }

  async function removeConversation(id: string) {
    if (streaming) return;
    try {
      await deleteConversation(id);
      setConvos((cs) => cs.filter((c) => c.id !== id));
      if (activeId === id) newConversation();
    } catch (e) {
      console.error(e);
    }
  }

  function sendMessage(options: { preferCloud?: boolean } = {}) {
    const text = draft.trim();
    if ((!text && pendingFiles.length === 0) || streaming) return;
    setDraft('');
    const fileIds = pendingFiles.map((f) => f.id);
    const fileNote = pendingFiles.length
      ? (text ? `${text}\n\n` : '') +
        `📎 ${pendingFiles.map((f) => f.filename).join(', ')}`
      : text;
    setPendingFiles([]);

    const userMsg: Message = { role: 'user', content: fileNote };
    const assistantMsg: Message = { role: 'assistant', content: '' };
    setMessages((ms) => [...ms, userMsg, assistantMsg]);
    setStreaming(true);
    let streamedAudioChunks = 0;
    if (voiceEnabled) {
      void import('../lib/streamingAudio').then(({ startTurn }) => startTurn());
    }

    abortRef.current = streamChat(
      {
        messages: [{ role: 'user', content: text || '(allegato)' }],
        conversationId: activeId ?? undefined,
        fileIds,
        preferCloud: options.preferCloud,
      },
      {
        onMeta: (cid) => {
          if (!activeId) {
            setActiveId(cid);
            listConversations().then(setConvos).catch(console.error);
          }
        },
        onToken: (t) => {
          setMessages((ms) => {
            const copy = ms.slice();
            const last = copy[copy.length - 1];
            if (last?.role === 'assistant') {
              copy[copy.length - 1] = { ...last, content: last.content + t };
            }
            return copy;
          });
        },
        onAudioChunk: (chunk) => {
          if (!voiceEnabled) return;
          streamedAudioChunks += 1;
          void import('../lib/streamingAudio').then(({ enqueueAudioChunk }) => {
            enqueueAudioChunk(chunk.audio_b64, {
              seq: chunk.seq, text: chunk.text, voiceId: chunk.voice_id,
            });
          });
        },
        onDone: async (stats) => {
          let toolResults: Array<{ ok: boolean; detail: string }> | undefined;
          let cleanedContent: string | undefined;
          setMessages((ms) => {
            const copy = ms.slice();
            const last = copy[copy.length - 1];
            if (last?.role === 'assistant') {
              const parsed = parseToolCalls(last.content);
              cleanedContent = ensureSomeProse(parsed.cleaned, parsed.toolCalls);
              copy[copy.length - 1] = {
                ...last,
                content: cleanedContent,
                tokensPerSecond: stats.tokensPerSecond,
                firstTokenSeconds: stats.firstTokenSeconds,
              };
              // Speak only if streaming TTS didn't cover the whole reply.
              // streamedAudioChunks > 0 means audio is already playing
              // sentence-by-sentence; calling speak() would double up.
              if (voiceEnabled && cleanedContent && streamedAudioChunks === 0) {
                speak(cleanedContent, { lang: 'it' });
              } else if (voiceEnabled && streamedAudioChunks > 0) {
                void import('../lib/streamingAudio').then(({ endTurn }) => endTurn());
              }
              if (parsed.toolCalls.length > 0) {
                void executeTools(parsed.toolCalls, {
                  radio: { playStation: radioPlayer.playStation, stop: radioPlayer.stop },
                  speak: voiceEnabled ? (text: string) => speak(text, { lang: 'it' }) : undefined,
                  openContent: cdaPlayer.open,
                }).then((results) => {
                  toolResults = results.map((r) => ({ ok: r.ok, detail: r.detail }));
                  setMessages((ms2) => {
                    const c2 = ms2.slice();
                    const idx = c2.length - 1;
                    if (c2[idx]?.role === 'assistant') {
                      c2[idx] = { ...c2[idx], toolResults };
                    }
                    return c2;
                  });
                });
              }
            }
            return copy;
          });
          setStreaming(false);
          abortRef.current = null;
        },
        onRevision: (text: string) => {
          setMessages((ms) => {
            const copy = ms.slice();
            const last = copy[copy.length - 1];
            if (last?.role === 'assistant') {
              copy[copy.length - 1] = { ...last, content: text, revised: true };
            }
            return copy;
          });
        },
        onError: (detail) => {
          setMessages((ms) => [
            ...ms.slice(0, -1),
            { role: 'assistant', content: `⚠️ ${detail}` },
          ]);
          setStreaming(false);
          abortRef.current = null;
        },
      },
    );
  }

  function stopStreaming() {
    abortRef.current?.();
    abortRef.current = null;
    setStreaming(false);
    void import('../lib/streamingAudio').then(({ clear }) => clear());
  }

  async function analyzeAttachment(f: { id: string; filename: string; kind: string; raw?: File }) {
    if (!f.raw || workflowBusy) return;
    setWorkflowBusy(true);
    setWorkflowResult(null);
    try {
      const isImage = f.kind === 'image' || /\.(jpg|jpeg|png|webp|heic)$/i.test(f.filename);
      const isPdf = f.kind === 'pdf' || /\.pdf$/i.test(f.filename);
      const b64 = await fileToBase64(f.raw);
      const args: { image_b64?: string; pdf_b64?: string } = {};
      if (isImage) args.image_b64 = b64;
      else if (isPdf) args.pdf_b64 = b64;
      else {
        // Other types fall back to text upload — read as text.
        const text = await f.raw.text();
        const resp = await runWorkflow({ text });
        if (resp.matched) setWorkflowResult({ response: resp, rerunArgs: { text } });
        return;
      }
      const resp = await runWorkflow(args);
      if (!resp.matched) {
        // No workflow recognised — silently let the file be a chat attachment.
        return;
      }
      setWorkflowResult({ response: resp, rerunArgs: args });
    } catch (err) {
      console.error('workflow analyze failed', err);
    } finally {
      setWorkflowBusy(false);
    }
  }

  async function handleFiles(files: FileList | File[]) {
    if (!files) return;
    setUploading(true);
    try {
      for (const f of Array.from(files)) {
        try {
          const { uploadFile } = await import('../api/files');
          const meta = await uploadFile(f);
          setPendingFiles((cur) => [
            ...cur,
            { id: meta.id, filename: meta.filename, kind: meta.kind, raw: f },
          ]);
        } catch (err) {
          console.error('upload failed', err);
        }
      }
    } finally {
      setUploading(false);
    }
  }

  function toggleListening() {
    if (listening) {
      listenRef.current?.stop();
      listenRef.current = null;
      setListening(false);
      return;
    }
    const handle = startListening({
      lang: 'it',
      interim: false,
      onText: (text, isFinal) => {
        if (isFinal && text.trim()) {
          setDraft(text.trim());
        }
      },
      onEnd: () => {
        listenRef.current = null;
        setListening(false);
      },
      onError: () => {
        listenRef.current = null;
        setListening(false);
      },
    });
    if (handle) {
      listenRef.current = handle;
      setListening(true);
    }
  }

  function selectAndCloseSidebar(id: string) {
    void selectConvo(id);
    setSidebarOpen(false);
  }

  function newAndCloseSidebar() {
    newConversation();
    setSidebarOpen(false);
  }

  return (
    <div className="flex flex-1 bg-bg text-fg relative h-full">
      {/* Mobile drawer backdrop */}
      {sidebarOpen && (
        <button
          type="button"
          aria-label="chiudi menu"
          className="md:hidden fixed inset-0 z-20 bg-fg/40 backdrop-blur-sm"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* ── Conversations sidebar ───────────────────────────── */}
      <aside
        className={cn(
          'fixed md:relative z-30 inset-y-0 left-0',
          'w-72 md:w-64 shrink-0 border-r border-fg/8',
          'bg-bg md:bg-surface1/40',
          'flex flex-col transition-transform duration-260 ease-spring',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full',
          'md:translate-x-0',
        )}
      >
        <div className="p-4">
          <button
            type="button"
            onClick={newAndCloseSidebar}
            disabled={streaming}
            className={cn(
              'w-full inline-flex items-center justify-center gap-2 rounded-pill',
              'bg-accent text-ivory shadow-warm hover:bg-accent-dark',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              'h-10 text-sm font-medium transition-all duration-180 ease-spring',
            )}
          >
            <Icon name="plus" size={16} />
            Nuova chat
          </button>
        </div>

        <div className="px-4 pb-2 text-2xs uppercase tracking-wider text-fg-muted">
          Conversazioni
        </div>

        <nav className="flex-1 overflow-y-auto px-2 space-y-0.5">
          {convos.map((c) => {
            const active = activeId === c.id;
            return (
              <div
                key={c.id}
                className={cn(
                  'group flex items-center gap-2 rounded-md px-3 py-2 text-sm cursor-pointer',
                  'transition-all duration-180',
                  active
                    ? 'bg-accent/12 text-fg ring-1 ring-accent/30'
                    : 'text-fg-soft hover:bg-surface1 hover:text-fg',
                )}
                onClick={() => selectAndCloseSidebar(c.id)}
              >
                <Icon
                  name="chat"
                  size={14}
                  className={active ? 'text-accent shrink-0' : 'text-fg-muted shrink-0'}
                />
                <span className="flex-1 truncate">{c.title}</span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeConversation(c.id);
                  }}
                  className={cn(
                    'p-1 -mr-1 rounded-pill text-fg-muted hover:text-alert hover:bg-alert/10',
                    'md:opacity-0 md:group-hover:opacity-100',
                  )}
                  aria-label="elimina"
                >
                  <Icon name="trash" size={13} />
                </button>
              </div>
            );
          })}
          {convos.length === 0 && (
            <p className="text-xs text-fg-muted px-3 py-3 text-center">
              Nessuna conversazione ancora.
            </p>
          )}
        </nav>

        <div className="border-t border-fg/8 px-4 py-3 text-xs text-fg-muted">
          <div className="flex items-center gap-2">
            <span className="h-7 w-7 rounded-pill bg-accent/15 text-accent flex items-center justify-center">
              <Icon name="profile" size={14} />
            </span>
            <span className="truncate" title={user.email}>
              {user.full_name ?? user.email}
            </span>
          </div>
        </div>
      </aside>

      {/* ── Main column ─────────────────────────────────────── */}
      <main className="flex-1 min-w-0 flex flex-col">
        <header className="border-b border-fg/8 px-4 md:px-6 py-3 flex items-center gap-3 bg-bg/80 backdrop-blur-sm">
          <IconButton
            name="plus"
            label="Menù conversazioni"
            size="sm"
            variant="plain"
            onClick={() => setSidebarOpen((v) => !v)}
            className="md:hidden"
          />

          <div className="shrink-0">
            <CaraFaceFX
              {...chatFaceFXState(streaming, messages)}
              size={36}
              particles={false}
              glow
            />
          </div>

          <div className="text-sm flex-1 min-w-0">
            <p className="font-display text-md text-fg leading-tight truncate">Cara</p>
            <p className="text-2xs text-fg-muted truncate">
              {streaming ? (
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-accent animate-breathe" />
                  sto scrivendo…
                </span>
              ) : (
                'pronta'
              )}
            </p>
          </div>

          {ttsOk && (
            <button
              type="button"
              onClick={() => {
                if (voiceEnabled && isSpeaking()) stopSpeaking();
                setVoiceEnabled((v) => !v);
              }}
              title={voiceEnabled ? 'Voce attiva — tocca per disattivare' : 'Voce disattivata'}
              className={cn(
                'inline-flex items-center justify-center h-10 w-10 rounded-pill shrink-0',
                'transition-all duration-180 ease-spring',
                voiceEnabled
                  ? 'bg-accent/15 text-accent ring-1 ring-accent/35'
                  : 'text-fg-muted hover:text-fg hover:bg-surface1',
              )}
              aria-label="Voce TTS"
            >
              <Icon name={voiceEnabled ? 'spark' : 'sparkle'} size={18} />
            </button>
          )}
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-3 md:px-6 py-5 space-y-3">
          <div className="max-w-3xl mx-auto space-y-3">
            {messages.length === 0 && (
              <WelcomeScreen
                onPick={(t) => setDraft(t)}
                userName={user.full_name?.split(' ')[0] ?? user.email.split('@')[0]}
              />
            )}
            {messages.map((m, i) => (
              <MessageBubble key={m.id ?? i} message={m} />
            ))}
            {workflowResult && (
              <WorkflowPreview
                result={workflowResult.response}
                rerunArgs={workflowResult.rerunArgs}
                onConfirmed={() => setWorkflowResult(null)}
                onCancelled={() => setWorkflowResult(null)}
              />
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Composer */}
        <div className="border-t border-fg/8 px-3 md:px-6 py-3 pb-[max(env(safe-area-inset-bottom),0.75rem)] space-y-2 bg-bg/85 backdrop-blur-sm">
          <div className="max-w-3xl mx-auto space-y-2">
            {pendingFiles.length > 0 && (
              <div className="flex flex-wrap gap-2 items-center">
                {pendingFiles.map((f) => {
                  const analyzable = f.raw && (
                    f.kind === 'image' || f.kind === 'pdf'
                    || /\.(jpg|jpeg|png|webp|heic|pdf)$/i.test(f.filename)
                  );
                  return (
                    <Badge key={f.id} tone="accent" size="md" className="!gap-1.5 pr-1">
                      <Icon name="note" size={12} />
                      <span className="max-w-[200px] truncate">{f.filename}</span>
                      {analyzable && !workflowResult && (
                        <button
                          type="button"
                          onClick={() => void analyzeAttachment(f)}
                          disabled={workflowBusy}
                          className={cn(
                            'ml-1 inline-flex items-center gap-1 rounded-pill px-2 py-0.5',
                            'text-2xs bg-celebrate/20 text-celebrate hover:bg-celebrate/30',
                            'disabled:opacity-50',
                          )}
                          title="Analizza come scontrino / bolletta / ricetta"
                        >
                          <Icon name="sparkle" size={11} />
                          {workflowBusy ? 'analizzo…' : 'Analizza'}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setPendingFiles((cur) => cur.filter((x) => x.id !== f.id))}
                        className="ml-0.5 -mr-0.5 p-0.5 rounded-pill hover:bg-fg/10"
                        aria-label="rimuovi allegato"
                      >
                        <Icon name="close" size={11} />
                      </button>
                    </Badge>
                  );
                })}
              </div>
            )}

            <div
              className={cn(
                'flex items-end gap-2 rounded-2xl bg-surface1 ring-1 transition-all duration-180',
                listening
                  ? 'ring-2 ring-accent shadow-warm'
                  : 'ring-fg/8 focus-within:ring-2 focus-within:ring-accent focus-within:bg-bg',
              )}
            >
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                  }
                }}
                placeholder={
                  listening
                    ? 'Parla pure…'
                    : pendingFiles.length
                      ? 'Cosa vuoi sapere su questo file?'
                      : 'Scrivi un messaggio… (Shift+Invio per nuova riga)'
                }
                rows={1}
                className={cn(
                  'flex-1 bg-transparent border-0 resize-none focus:outline-none focus:ring-0',
                  'px-4 py-3 text-[15px] leading-relaxed text-fg placeholder:text-fg-muted',
                  'max-h-40 min-h-[44px]',
                )}
                disabled={streaming || listening}
              />

              <div className="flex items-center gap-1 pr-2 pb-1.5">
                <label
                  className={cn(
                    'inline-flex items-center justify-center h-9 w-9 rounded-pill cursor-pointer',
                    'text-fg-muted hover:text-fg hover:bg-surface2 transition-all',
                    uploading && 'opacity-50 cursor-not-allowed',
                  )}
                  title="Allega un file (PDF, DOCX, TXT, CSV, XLSX)"
                  aria-label="Allega file"
                >
                  {uploading ? (
                    <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                  ) : (
                    <Icon name="note" size={17} />
                  )}
                  <input
                    type="file"
                    multiple
                    accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.json,.yaml,.yml"
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files) handleFiles(e.target.files);
                      e.target.value = '';
                    }}
                    disabled={uploading || streaming}
                  />
                </label>

                {sttOk && !streaming && (
                  <button
                    type="button"
                    onClick={toggleListening}
                    title={listening ? 'Stop ascolto' : 'Detta con microfono'}
                    aria-label="Detta"
                    className={cn(
                      'inline-flex items-center justify-center h-9 w-9 rounded-pill',
                      'transition-all duration-180 ease-spring',
                      listening
                        ? 'bg-alert text-ivory ring-2 ring-alert/40 animate-breathe'
                        : 'text-fg-muted hover:text-fg hover:bg-surface2',
                    )}
                  >
                    <Icon name="mic" size={17} />
                  </button>
                )}

                {streaming ? (
                  <button
                    type="button"
                    onClick={stopStreaming}
                    className={cn(
                      'inline-flex items-center justify-center h-10 px-4 rounded-pill',
                      'bg-alert text-ivory shadow-warm hover:opacity-90',
                      'text-sm font-medium transition-all',
                    )}
                  >
                    Stop
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => sendMessage({ preferCloud: true })}
                      disabled={!draft.trim() && pendingFiles.length === 0}
                      title="Risposta migliore con AI cloud (privacy: solo questo turno)"
                      aria-label="Risposta migliore"
                      className={cn(
                        'inline-flex items-center justify-center h-9 w-9 rounded-pill',
                        'text-celebrate hover:bg-celebrate/12',
                        'disabled:opacity-30 disabled:cursor-not-allowed',
                        'transition-all duration-180 ease-spring',
                      )}
                    >
                      <Icon name="sparkle" size={17} />
                    </button>
                    <button
                      type="button"
                      onClick={() => sendMessage()}
                      disabled={!draft.trim() && pendingFiles.length === 0}
                      aria-label="Invia"
                      className={cn(
                        'inline-flex items-center justify-center h-10 w-10 rounded-pill',
                        'bg-accent text-ivory shadow-warm hover:bg-accent-dark',
                        'disabled:opacity-40 disabled:cursor-not-allowed disabled:bg-surface2 disabled:text-fg-muted',
                        'transition-all duration-180 ease-spring',
                      )}
                    >
                      <Icon name="send" size={18} />
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
