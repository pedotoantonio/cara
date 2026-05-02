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
import { useRadioPlayer } from '../lib/radioPlayer';
import { ensureSomeProse, executeTools, parseToolCalls } from '../lib/tools';
import type { Conversation, Message } from '../types/chat';
import { CaraFaceFX } from './CaraFaceFX';
import { MessageBubble } from './MessageBubble';
import { WelcomeScreen } from './WelcomeScreen';

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
  const [sidebarOpen, setSidebarOpen] = useState(false); // mobile drawer
  const radioPlayer = useRadioPlayer();
  const [pendingFiles, setPendingFiles] = useState<{ id: string; filename: string; kind: string }[]>([]);
  const [uploading, setUploading] = useState(false);
  const abortRef = useRef<(() => void) | null>(null);
  const listenRef = useRef<ListenHandle | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const ttsOk = ttsAvailable();
  const sttOk = sttAvailable();

  // Persist voice toggle
  useEffect(() => {
    const cur = loadPrefs();
    savePrefs({ ...cur, voiceEnabled });
  }, [voiceEnabled]);

  // Stop any in-flight speech when leaving the page
  useEffect(() => () => stopSpeaking(), []);

  // Initial load
  useEffect(() => {
    listConversations().then(setConvos).catch(console.error);
  }, []);

  // Auto-scroll on new content
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

  function sendMessage() {
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

    abortRef.current = streamChat(
      {
        messages: [{ role: 'user', content: text || '(allegato)' }],
        conversationId: activeId ?? undefined,
        fileIds,
      },
      {
        onMeta: (cid) => {
          if (!activeId) {
            setActiveId(cid);
            // refresh sidebar so the new conv appears at top
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
        onDone: async (stats) => {
          // Pull tool calls out of the final assistant content, execute them,
          // strip them from the user-visible text and surface results inline.
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
              // Speak the cleaned reply if TTS is enabled.
              if (voiceEnabled && cleanedContent) {
                speak(cleanedContent, { lang: 'it' });
              }
              if (parsed.toolCalls.length > 0) {
                // Execute outside the setState callback (async).
                void executeTools(parsed.toolCalls, {
                  radio: { playStation: radioPlayer.playStation, stop: radioPlayer.stop },
                  speak: voiceEnabled ? (text: string) => speak(text, { lang: 'it' }) : undefined,
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
  }

  async function handleFiles(files: FileList | File[]) {
    if (!files) return;
    setUploading(true);
    try {
      for (const f of Array.from(files)) {
        try {
          // Lazy-import to avoid pulling the helper into legacy chunks.
          const { uploadFile } = await import('../api/files');
          const meta = await uploadFile(f);
          setPendingFiles((cur) => [
            ...cur,
            { id: meta.id, filename: meta.filename, kind: meta.kind },
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
    <div className="flex flex-1 bg-slate-900 text-slate-100 relative">
      {/* Mobile drawer backdrop */}
      {sidebarOpen && (
        <button
          type="button"
          aria-label="chiudi menu"
          className="md:hidden fixed inset-0 z-20 bg-black/50"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar conversations: drawer on mobile, fixed-position on md+ */}
      <aside
        className={`
          fixed md:relative z-30 inset-y-0 left-0
          w-72 md:w-64 shrink-0 border-r border-slate-800 bg-slate-900 md:bg-transparent
          flex flex-col transition-transform duration-200
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0
        `}
      >
        <div className="p-4 border-b border-slate-800">
          <button
            type="button"
            onClick={newAndCloseSidebar}
            disabled={streaming}
            className="w-full rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-3 py-2 text-sm font-medium"
          >
            + Nuova chat
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto p-2 space-y-1">
          {convos.map((c) => (
            <div
              key={c.id}
              className={`group flex items-center gap-2 rounded-lg px-3 py-2 text-sm cursor-pointer ${
                activeId === c.id
                  ? 'bg-slate-800 text-slate-50'
                  : 'hover:bg-slate-800/60 text-slate-300'
              }`}
              onClick={() => selectAndCloseSidebar(c.id)}
            >
              <span className="flex-1 truncate">{c.title}</span>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  removeConversation(c.id);
                }}
                className="md:opacity-0 md:group-hover:opacity-100 text-slate-500 hover:text-rose-400 px-1"
                aria-label="elimina"
              >
                ×
              </button>
            </div>
          ))}
          {convos.length === 0 && (
            <p className="text-xs text-slate-500 px-3 py-2">Nessuna conversazione</p>
          )}
        </nav>
        <div className="border-t border-slate-800 p-3 text-xs text-slate-500">
          <div className="truncate" title={user.email}>
            {user.full_name ?? user.email}
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 min-w-0 flex flex-col">
        <header className="border-b border-slate-800 px-4 md:px-6 py-3 flex items-center gap-3">
          {/* Hamburger toggle, mobile only */}
          <button
            type="button"
            onClick={() => setSidebarOpen((v) => !v)}
            aria-label="menu conversazioni"
            className="md:hidden w-9 h-9 rounded-xl hover:bg-slate-800 flex items-center justify-center text-slate-300"
          >
            ☰
          </button>
          <CaraFaceFX
            {...chatFaceFXState(streaming, messages)}
            size={36}
            particles={false}
            glow
          />
          <div className="text-sm flex-1 min-w-0">
            <p className="font-medium truncate">CARA</p>
            <p className="text-xs text-slate-500 truncate">
              {streaming ? 'sto scrivendo…' : 'pronta'}
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
              className={`text-lg w-9 h-9 shrink-0 rounded-xl ${
                voiceEnabled
                  ? 'bg-emerald-500/20 ring-1 ring-emerald-500/40'
                  : 'hover:bg-slate-800 text-slate-500'
              }`}
            >
              {voiceEnabled ? '🔊' : '🔈'}
            </button>
          )}
        </header>
        <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-3">
          {messages.length === 0 && <WelcomeScreen onPick={(t) => setDraft(t)} userName={user.full_name ?? user.email.split('@')[0]} />}
          {messages.map((m, i) => (
            <MessageBubble key={m.id ?? i} message={m} />
          ))}
          <div ref={bottomRef} />
        </div>

        <div className="border-t border-slate-800 p-3 md:p-4 pb-[max(env(safe-area-inset-bottom),0.75rem)] space-y-2">
          {pendingFiles.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {pendingFiles.map((f) => (
                <span
                  key={f.id}
                  className="inline-flex items-center gap-2 rounded-full bg-emerald-500/15 border border-emerald-500/40 px-3 py-1 text-xs text-emerald-200"
                  title={`${f.kind} · pronto per la prossima domanda`}
                >
                  📎 {f.filename}
                  <button
                    type="button"
                    onClick={() => setPendingFiles((cur) => cur.filter((x) => x.id !== f.id))}
                    className="text-emerald-300 hover:text-rose-300"
                    aria-label="rimuovi allegato"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="flex gap-2 items-end">
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
                listening ? 'Parla pure…'
                  : pendingFiles.length
                    ? 'Cosa vuoi sapere su questo file?'
                    : 'Scrivi un messaggio… (Shift+Invio per nuova riga)'
              }
              rows={1}
              className="flex-1 resize-none rounded-xl bg-slate-800 border border-slate-700 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50 max-h-40"
              disabled={streaming || listening}
            />
            <label
              className={`w-12 h-12 rounded-xl text-lg flex items-center justify-center cursor-pointer ${
                uploading
                  ? 'bg-slate-700 text-slate-500'
                  : 'bg-slate-800 hover:bg-slate-700 border border-slate-700'
              }`}
              title="Allega un file (PDF, DOCX, TXT, CSV, XLSX)"
            >
              {uploading ? '…' : '📎'}
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
                className={`w-12 h-12 rounded-xl text-lg ${
                  listening
                    ? 'bg-rose-500/30 ring-1 ring-rose-500/60 animate-pulse'
                    : 'bg-slate-800 hover:bg-slate-700 border border-slate-700'
                }`}
              >
                {listening ? '⏹' : '🎤'}
              </button>
            )}
            {streaming ? (
              <button
                type="button"
                onClick={stopStreaming}
                className="rounded-xl bg-rose-600 hover:bg-rose-500 px-4 py-3 text-sm font-medium"
              >
                Stop
              </button>
            ) : (
              <button
                type="button"
                onClick={sendMessage}
                disabled={!draft.trim()}
                className="rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-4 py-3 text-sm font-medium"
              >
                Invia
              </button>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
