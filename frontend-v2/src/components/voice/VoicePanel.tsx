// VoicePanel — modale voice-first dal CTA HomePage o long-press FloatingAvatar.
// Usa il MicPipeline portato da v1 (MediaRecorder + AnalyserNode + VAD).

import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Microphone, X, ArrowsClockwise } from '@phosphor-icons/react';
import { Button, useToast } from '@/design/components';
import { AudioLevelMeter } from './AudioLevelMeter';
import { startMicSession, type MicSession, type MicPipelineDiagnostics } from '@/lib/micPipeline';
import { transcribeBlob, type AsrResult } from '@/api/asr';
import { useAvatarStore } from '@/state/avatar';
import { requestMic } from '@/hooks/usePermissions';

interface VoicePanelProps {
  open: boolean;
  onClose: () => void;
}

type Phase = 'idle' | 'permission' | 'listening' | 'transcribing' | 'done' | 'error';

export function VoicePanel({ open, onClose }: VoicePanelProps) {
  const toast = useToast();
  const setAvatar = useAvatarStore((s) => s.setAvatar);

  const [phase, setPhase] = useState<Phase>('idle');
  const [level, setLevel] = useState(0);
  const [levelDb, setLevelDb] = useState(-90);
  const [transcript, setTranscript] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const sessionRef = useRef<MicSession | null>(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    if (open) {
      cancelledRef.current = false;
      void start();
    } else {
      cancelledRef.current = true;
      abortSession();
      setPhase('idle');
      setTranscript('');
      setErrorMsg(null);
      setLevel(0);
      setLevelDb(-90);
    }
    return () => {
      cancelledRef.current = true;
      abortSession();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function abortSession() {
    if (sessionRef.current) {
      try {
        sessionRef.current.abort();
      } catch {
        /* noop */
      }
      sessionRef.current = null;
    }
  }

  async function start() {
    setErrorMsg(null);
    setTranscript('');
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
          // Throttle via rAF — il pipeline emette ~60 Hz, React setState
          // batchato è OK ma evitiamo work inutile durante alta freq.
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
        setErrorMsg(sanity.canned_reply);
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
      setPhase('done');
      toast.push({ tone: 'mint', title: 'Ti ho sentito', body: text.slice(0, 120) });
      setAvatar({ energy: 'idle', emotion: 'happy', caption: text.slice(0, 60) });
      console.log('[cara-mic] ok', { text, confidence: result.confidence_label, diag });
      // TODO M3: send to chat backend, stream reply, TTS playback inline.
    } catch (err) {
      setPhase('error');
      setErrorMsg((err as Error).message || 'Errore di rete sull\'ASR.');
      setAvatar({ energy: 'idle', emotion: 'sad', caption: null });
    }
  }

  function userStop() {
    void finishRecording();
  }

  function userCancel() {
    abortSession();
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

            <div className="my-4">
              <motion.div
                animate={phase === 'listening' ? { scale: [1, 1.06, 1] } : { scale: 1 }}
                transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
                className="inline-flex items-center justify-center w-32 h-32 rounded-full bg-accent-coral/12 mb-4"
              >
                <Microphone
                  size={56}
                  weight={phase === 'listening' ? 'fill' : 'duotone'}
                  className="text-accent-coral"
                />
              </motion.div>
              <h2 className="font-display text-2xl text-text-primary">
                {phase === 'permission' && 'Un attimo…'}
                {phase === 'listening' && 'Sto ascoltando'}
                {phase === 'transcribing' && 'Sto capendo'}
                {phase === 'done' && 'Eccoci'}
                {phase === 'error' && 'Qualcosa è andato storto'}
                {phase === 'idle' && 'Tocca per parlare'}
              </h2>
            </div>

            {phase === 'listening' && (
              <div className="flex justify-center">
                <AudioLevelMeter db={levelDb} level={level} active />
              </div>
            )}

            {transcript && (
              <p className="mt-4 text-lg text-text-primary leading-relaxed">"{transcript}"</p>
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
              {(phase === 'done' || phase === 'error') && (
                <>
                  <Button
                    size="lg"
                    fullWidth
                    leftIcon={<ArrowsClockwise size={18} />}
                    onClick={start}
                  >
                    Riprova
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
