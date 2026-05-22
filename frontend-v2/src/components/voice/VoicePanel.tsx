// VoicePanel — modale voice-first end-to-end.
// Pipeline: mic → MediaRecorder → Whisper ASR → sanity check → chat SSE
// streaming → token + audio_chunk Piper playback inline → avatar reagisce.
//
// Aperto da:
//   - CTA "Parla con me" nella Hub Casa
//   - Long-press sul FloatingAvatar (qualsiasi page tranne home)

import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Microphone, X, ArrowsClockwise } from '@phosphor-icons/react';
import { Button } from '@/design/components';
import { CaraFace } from '@/components/avatar/CaraFace';
import { AudioLevelMeter } from './AudioLevelMeter';
import { startMicSession, type MicSession, type MicPipelineDiagnostics } from '@/lib/micPipeline';
import { transcribeBlob, type AsrResult } from '@/api/asr';
import { useAvatarStore } from '@/state/avatar';
import { requestMic } from '@/hooks/usePermissions';
import { streamChat } from '@/api/chat';
import {
  consumeChatStream,
  type ChatTokenPayload,
  type ChatAudioChunkPayload,
  type ChatMetaPayload,
} from '@/lib/chatStream';
import { createTtsPlayer, type TtsPlayer } from '@/lib/ttsPlayback';

interface VoicePanelProps {
  open: boolean;
  onClose: () => void;
}

type Phase =
  | 'idle'
  | 'permission'
  | 'listening'
  | 'transcribing'
  | 'confirming'   // trascritto a bassa confidenza → chiedi conferma prima di mandare alla chat
  | 'thinking'
  | 'speaking'
  | 'done'
  | 'error';

export function VoicePanel({ open, onClose }: VoicePanelProps) {
  const setAvatar = useAvatarStore((s) => s.setAvatar);

  const [phase, setPhase] = useState<Phase>('idle');
  const [level, setLevel] = useState(0);
  const [levelDb, setLevelDb] = useState(-90);
  const [transcript, setTranscript] = useState('');
  const [reply, setReply] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const sessionRef = useRef<MicSession | null>(null);
  const ttsRef = useRef<TtsPlayer | null>(null);
  const chatAbortRef = useRef<AbortController | null>(null);
  const cancelledRef = useRef(false);
  /**
   * Conversation id catturato dal primo turno voice (event `meta`).
   * Riusato per ogni "Parla ancora" successivo dentro la stessa sessione
   * del pannello — così il backend carica la history e l'LLM ha context.
   * Senza questo, ogni turno è isolato e il 1.5B Qwen risponde "inventando"
   * perché vede solo il singolo messaggio corrente.
   * Reset a null quando il pannello si chiude (nuova sessione = nuova convo).
   */
  const voiceConvIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (open) {
      cancelledRef.current = false;
      void start();
    } else {
      cancelledRef.current = true;
      abortAll();
      setPhase('idle');
      setTranscript('');
      setReply('');
      setErrorMsg(null);
      setLevel(0);
      setLevelDb(-90);
      // Reset conversation id quando il pannello si chiude — la prossima
      // apertura inizia una conversazione voice nuova.
      voiceConvIdRef.current = null;
    }
    return () => {
      cancelledRef.current = true;
      abortAll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function abortAll() {
    if (sessionRef.current) {
      try {
        sessionRef.current.abort();
      } catch {
        /* noop */
      }
      sessionRef.current = null;
    }
    if (chatAbortRef.current) {
      chatAbortRef.current.abort();
      chatAbortRef.current = null;
    }
    if (ttsRef.current) {
      ttsRef.current.stop();
      ttsRef.current = null;
    }
  }

  async function start() {
    setErrorMsg(null);
    setTranscript('');
    setReply('');
    setPhase('permission');
    setAvatar({ energy: 'listening', emotion: 'neutral', glowAccent: 'coral', caption: 'Ti ascolto…' });

    const granted = await requestMic();
    if (granted !== 'granted') {
      setPhase('error');
      setErrorMsg(
        granted === 'denied'
          ? 'Permesso microfono negato. Concedi l\'accesso dalla barra del browser e riprova.'
          : 'Microfono non disponibile su questo dispositivo.',
      );
      setAvatar({ energy: 'idle', emotion: 'sad', caption: null });
      return;
    }

    try {
      sessionRef.current = await startMicSession({
        vadMode: 'auto',
        onLevel: (db, normalised) => {
          setLevel(normalised);
          setLevelDb(db);
        },
        onAutoStop: () => {
          void finishRecording();
        },
      });
      setPhase('listening');
    } catch (err) {
      setPhase('error');
      setErrorMsg((err as Error).message || 'Impossibile aprire il microfono.');
      setAvatar({ energy: 'idle', emotion: 'sad', caption: null });
    }
  }

  async function finishRecording() {
    if (cancelledRef.current || !sessionRef.current) return;
    setPhase('transcribing');
    setAvatar({ energy: 'thinking', emotion: 'thoughtful', caption: 'Sto capendo…' });

    let blob: Blob | null = null;
    let diag: MicPipelineDiagnostics | null = null;
    try {
      const res = await sessionRef.current.stop();
      blob = res.blob;
      diag = res.diag;
    } catch (err) {
      setPhase('error');
      setErrorMsg((err as Error).message || 'Errore nella registrazione.');
      setAvatar({ energy: 'idle', emotion: 'sad', caption: null });
      return;
    } finally {
      sessionRef.current = null;
    }

    if (!blob || blob.size < 1000) {
      setPhase('error');
      setErrorMsg('Non ho sentito niente. Riprova più vicino al microfono.');
      setAvatar({ energy: 'idle', emotion: 'confused', caption: null });
      console.log('[cara-mic] empty blob', diag);
      return;
    }

    try {
      const result: AsrResult = await transcribeBlob(blob, 'it');
      const text = result.text?.trim() ?? '';
      const sanity = result.sanity;
      if (sanity && !sanity.ok && sanity.canned_reply) {
        setTranscript('');
        setReply(sanity.canned_reply);
        setPhase('done');
        setAvatar({ energy: 'idle', emotion: 'confused', caption: sanity.canned_reply });
        console.log('[cara-mic] sanity rejected', sanity.reason, diag);
        return;
      }
      if (!text) {
        setPhase('error');
        setErrorMsg('Non ho capito. Prova di nuovo.');
        setAvatar({ energy: 'idle', emotion: 'confused', caption: null });
        console.log('[cara-mic] empty transcript', diag);
        return;
      }
      setTranscript(text);
      console.log('[cara-mic] transcribed', { text, confidence: result.confidence_label, diag });

      // Confidence gate: se la trascrizione è incerta (low/medium o frase
      // molto corta), chiedi conferma all'utente PRIMA di mandare il
      // transcript all'LLM. Evita la situazione 'Whisper ha trascritto
      // qualcosa di strano e CARA risponde a cazzo perché non capisce'.
      // Solo 'high' confidence va dritta in chat.
      const low =
        result.confidence_label === 'low' ||
        (result.confidence_label === 'medium' && text.split(/\s+/).length < 4);
      if (low) {
        setPhase('confirming');
        setAvatar({ energy: 'idle', emotion: 'confused', caption: 'Ho capito bene?', glowAccent: 'sun' });
        console.log('[cara-mic] low confidence, waiting confirm');
        return;
      }

      // Lancia la chat
      await runChatTurn(text);
    } catch (err) {
      setPhase('error');
      setErrorMsg((err as Error).message || 'Errore di rete sull\'ASR.');
      setAvatar({ energy: 'idle', emotion: 'sad', caption: null });
    }
  }

  /**
   * Manda il transcript al backend chat e gestisce lo stream SSE.
   *
   * Conversation_id: il PRIMO turno della sessione panel parte SENZA id
   * (backend ne crea una nuova + risponde con `meta.conversation_id`).
   * I turni successivi ("Parla ancora") riusano lo stesso id → backend
   * carica la history → l'LLM ha context multi-turn invece di rispondere
   * a freddo (la causa del bug 'risponde con informazioni inventate').
   */
  async function runChatTurn(userText: string) {
    if (cancelledRef.current) return;
    setPhase('thinking');
    setReply('');
    setAvatar({ energy: 'thinking', emotion: 'thoughtful', caption: 'Sto pensando…', glowAccent: 'lilac' });

    // TTS player con flag "speaking"
    ttsRef.current = createTtsPlayer();
    ttsRef.current.onComplete(() => {
      if (cancelledRef.current) return;
      setAvatar({ energy: 'idle', emotion: 'happy', caption: null, glowAccent: 'coral' });
    });

    chatAbortRef.current = new AbortController();
    let accumulated = '';
    let hasAudio = false;

    try {
      // Wrappa la trascrizione con un hint per l'LLM: dire esplicitamente
      // che è voce → il 1.5B tende a inventare se si sente "sicuro", ma se
      // gli diciamo che è una trascrizione potenzialmente imprecisa è più
      // probabile che chieda conferma invece di sparare risposte a caso.
      const wrappedContent =
        userText +
        '\n\n[Nota interna: questo è un messaggio vocale trascritto da microfono. ' +
        'Se la domanda è poco chiara, ambigua o incompleta, chiedi ' +
        "all'utente di ripetere o di chiarire invece di inventare una risposta. " +
        'Se non sai con certezza una informazione, dillo onestamente.]';

      const response = await streamChat(
        {
          messages: [{ role: 'user', content: wrappedContent }],
          max_new_tokens: 400,
        },
        voiceConvIdRef.current ?? undefined,
      );

      await consumeChatStream(
        response,
        (ev) => {
          if (cancelledRef.current) return;
          if (ev.type === 'meta') {
            const meta = ev.data as unknown as ChatMetaPayload;
            if (meta.conversation_id && !voiceConvIdRef.current) {
              voiceConvIdRef.current = meta.conversation_id;
              console.log('[cara-voice] captured conv_id', meta.conversation_id);
            }
          } else if (ev.type === 'token') {
            const tok = ev.data as unknown as ChatTokenPayload;
            const t = tok.text ?? '';
            if (t) {
              accumulated += t;
              setReply(accumulated);
              if (phase !== 'speaking') {
                setPhase('speaking');
              }
            }
          } else if (ev.type === 'audio_chunk') {
            const chunk = ev.data as unknown as ChatAudioChunkPayload;
            hasAudio = true;
            if (ttsRef.current) {
              ttsRef.current.enqueue(chunk);
            }
            setAvatar({ energy: 'speaking', emotion: 'happy', glowAccent: 'coral' });
          } else if (ev.type === 'done') {
            // Final state — done event reached
          } else if (ev.type === 'error') {
            throw new Error((ev.data as { detail?: string }).detail ?? 'Errore chat');
          }
        },
        chatAbortRef.current.signal,
      );

      if (cancelledRef.current) return;
      setPhase('done');
      // Se non c'erano audio_chunk, niente da aspettare → idle subito
      if (!hasAudio) {
        setAvatar({ energy: 'idle', emotion: 'happy', caption: null, glowAccent: 'coral' });
      }
      console.log('[cara-chat] done', { reply: accumulated.length, hasAudio });
    } catch (err) {
      if (cancelledRef.current) return;
      setPhase('error');
      setErrorMsg((err as Error).message || 'Errore chat');
      setAvatar({ energy: 'idle', emotion: 'sad', caption: null });
    }
  }

  function userStop() {
    void finishRecording();
  }

  function userCancel() {
    abortAll();
    onClose();
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 bg-bg-base/95 backdrop-blur-md grid place-items-center p-6"
          onClick={onClose}
        >
          <motion.div
            initial={{ scale: 0.94, y: 12 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.94, y: 12 }}
            transition={{ type: 'spring', damping: 22, stiffness: 240 }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md rounded-2xl bg-bg-elevated shadow-3 border border-border-soft p-6 text-center"
          >
            <div className="flex justify-end">
              <button
                onClick={onClose}
                className="p-2 -m-2 rounded-md text-text-muted hover:text-text-primary"
                aria-label="Chiudi"
              >
                <X size={22} />
              </button>
            </div>

            {/* Avatar / Mic visual */}
            <div className="my-3">
              {phase === 'thinking' || phase === 'speaking' || phase === 'done' ? (
                <div className="inline-flex">
                  <CaraFace
                    size={120}
                    energy={
                      phase === 'speaking'
                        ? 'speaking'
                        : phase === 'thinking'
                          ? 'thinking'
                          : 'idle'
                    }
                    emotion={phase === 'speaking' ? 'happy' : phase === 'thinking' ? 'thoughtful' : 'happy'}
                  />
                </div>
              ) : (
                <motion.div
                  animate={phase === 'listening' ? { scale: [1, 1.06, 1] } : { scale: 1 }}
                  transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
                  className="inline-flex items-center justify-center w-32 h-32 rounded-full bg-accent-coral/12"
                >
                  <Microphone
                    size={56}
                    weight={phase === 'listening' ? 'fill' : 'duotone'}
                    className="text-accent-coral"
                  />
                </motion.div>
              )}
              <h2 className="font-display text-2xl text-text-primary mt-3">
                {phase === 'permission' && 'Un attimo…'}
                {phase === 'listening' && 'Sto ascoltando'}
                {phase === 'transcribing' && 'Sto capendo'}
                {phase === 'confirming' && 'Ho capito bene?'}
                {phase === 'thinking' && 'Sto pensando'}
                {phase === 'speaking' && 'Eccomi'}
                {phase === 'done' && (reply ? '' : 'Tocca per parlare')}
                {phase === 'error' && 'Qualcosa è andato storto'}
                {phase === 'idle' && 'Tocca per parlare'}
              </h2>
            </div>

            {phase === 'listening' && (
              <div className="flex justify-center">
                <AudioLevelMeter db={levelDb} level={level} active />
              </div>
            )}

            {/* Trascritto utente */}
            {transcript && (
              <div className="mt-3 px-2">
                <p className="text-xs text-text-muted mb-1">Hai detto</p>
                <p className="text-sm text-text-secondary italic">"{transcript}"</p>
              </div>
            )}

            {/* Risposta CARA */}
            {reply && (
              <div className="mt-4 px-2">
                <p className="text-base text-text-primary leading-relaxed text-left">
                  {reply}
                  {phase === 'speaking' && (
                    <span className="inline-block w-1.5 h-4 ml-1 align-middle bg-current opacity-60 animate-pulse" />
                  )}
                </p>
              </div>
            )}

            {errorMsg && <p className="mt-4 text-sm text-accent-coral">{errorMsg}</p>}

            <div className="mt-6 flex flex-col gap-2">
              {phase === 'listening' && (
                <>
                  <Button size="lg" fullWidth onClick={userStop}>
                    Ho finito
                  </Button>
                  <Button size="sm" variant="ghost" onClick={userCancel}>
                    Annulla
                  </Button>
                </>
              )}
              {(phase === 'thinking' || phase === 'speaking') && (
                <Button size="sm" variant="ghost" onClick={userCancel}>
                  Annulla
                </Button>
              )}
              {phase === 'confirming' && (
                <>
                  <p className="text-sm text-text-secondary mb-1">
                    Confermi che hai detto questo o vuoi ripetere?
                  </p>
                  <Button
                    size="lg"
                    fullWidth
                    onClick={() => {
                      void runChatTurn(transcript);
                    }}
                  >
                    Sì, è giusto
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    leftIcon={<ArrowsClockwise size={14} />}
                    onClick={start}
                  >
                    Riprova
                  </Button>
                </>
              )}
              {(phase === 'done' || phase === 'error') && (
                <>
                  <Button
                    size="lg"
                    fullWidth
                    leftIcon={<ArrowsClockwise size={18} />}
                    onClick={start}
                  >
                    Parla ancora
                  </Button>
                  <Button size="sm" variant="ghost" onClick={onClose}>
                    Chiudi
                  </Button>
                </>
              )}
              {phase === 'transcribing' && (
                <div className="flex items-center justify-center text-sm text-text-muted">
                  <span className="inline-block h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin mr-2" />
                  Trascrizione in corso…
                </div>
              )}
              {phase === 'permission' && (
                <p className="text-sm text-text-muted">Concedi il permesso microfono se richiesto.</p>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
