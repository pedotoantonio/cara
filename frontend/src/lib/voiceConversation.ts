/**
 * Voice-first conversation hook for the home page.
 *
 * Owns the small state machine that ties together:
 *   - STT (interim transcript shown live as `userText`)
 *   - backend chat stream (assistant tokens accumulate into `assistantText`)
 *   - TTS playback (when each reply finishes, speak it aloud)
 *
 * Exposes:
 *   - `phase` — idle | listening | thinking | speaking
 *   - `userText` — the rolling STT transcript
 *   - `assistantText` — the assistant reply (full, not chunk-by-chunk)
 *   - `lastAssistantSpeak` — the text passed to TTS (used by LiveCaption to
 *     know when to start the karaoke cursor)
 *   - `start()`, `stop()`, `cancel()` controls
 *
 * Conversation persistence: a single conversation per browser session
 * (id stored in `voiceConversation.activeConvId`) so multi-turn memory
 * works across requests.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { setAiPhase } from './aiState';
import {
  startWhisperRecording,
  whisperRecorderAvailable,
  type WhisperRecorderHandle,
} from './whisperFallback';
import { streamChat } from '../api/chat';
import {
  speak,
  startListening,
  stopSpeaking,
  sttAvailable,
  ttsAvailable,
  type ListenHandle,
} from './speech';
import { startWakeWord, type WakeWordHandle } from './wakeWord';

export type VoicePhase = 'idle' | 'listening' | 'thinking' | 'speaking';

export interface VoiceConversation {
  phase: VoicePhase;
  userText: string;
  assistantText: string;
  /** The text that is actually being spoken (drives LiveCaption cursor). */
  lastAssistantSpeak: string;
  start: () => void;
  stop: () => void;
  cancel: () => void;
  ttsOk: boolean;
  sttOk: boolean;
  /** True if the background wake-word listener is active. */
  wakeWordActive: boolean;
  /** Last user-facing error (e.g. mic permission denied). UI shows a banner. */
  errorMessage: string | null;
  /** Dismiss the visible error banner. */
  dismissError: () => void;
}

export function useVoiceConversation(opts: {
  autoSpeak: boolean;
  /** Enable continuous "CARA …" wake-word listening in the background. */
  wakeWord?: boolean;
}): VoiceConversation {
  const [phase, setPhase] = useState<VoicePhase>('idle');
  const [userText, setUserText] = useState('');
  const [assistantText, setAssistantText] = useState('');
  const [lastAssistantSpeak, setLastAssistantSpeak] = useState('');
  const [convId, setConvId] = useState<string | null>(null);

  const listenRef = useRef<ListenHandle | null>(null);
  const whisperRef = useRef<WhisperRecorderHandle | null>(null);
  const abortStreamRef = useRef<(() => void) | null>(null);
  const wakeRef = useRef<WakeWordHandle | null>(null);
  const phaseRef = useRef<VoicePhase>('idle');
  const [wakeWordActive, setWakeWordActive] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // Latest interim STT transcript. Updated on every onText so we always have
  // it available — even if the recognizer never fires `isFinal` (a known iOS
  // Safari behaviour) or the user taps stop before completing the sentence.
  const interimRef = useRef('');
  // Set to true once we've submitted the current utterance, so onEnd doesn't
  // double-submit when the recognizer closes after the tap.
  const submittedRef = useRef(false);

  const ttsOk = ttsAvailable();
  // sttOk reflects "can we capture voice from this browser?" — true if
  // either the native SR API works OR we can record + send to whisper.
  // The voice paths above pick the right strategy.
  const sttOk = sttAvailable() || whisperRecorderAvailable();

  function logVoice(...args: unknown[]) {
    // Surface state transitions in the dev console with a stable prefix so
    // the user can capture them and forward us a copy when something fails.
    // eslint-disable-next-line no-console
    console.log('[cara-voice]', ...args);
  }

  function describeMicError(error: string): string {
    const e = error.toLowerCase();
    if (e.includes('not-allowed') || e.includes('permission'))
      return 'Microfono bloccato dal browser. Concedi il permesso e ricarica la pagina.';
    if (e.includes('no-speech'))
      return 'Non ho sentito niente. Riprova parlando più forte.';
    if (e.includes('audio-capture'))
      return 'Nessun microfono rilevato. Controlla il dispositivo audio.';
    if (e.includes('network'))
      return 'Errore di rete sul riconoscimento vocale. Riprova.';
    if (e.includes('aborted'))
      return '';   // user-initiated abort — silent
    return `Errore microfono: ${error}`;
  }

  const dismissError = useCallback(() => setErrorMessage(null), []);

  // Keep a ref to the phase so the wake-word callback can read it without
  // capturing a stale closure. Also publish the phase to the global AI state
  // singleton so the ambient banner can display it on any page.
  useEffect(() => {
    phaseRef.current = phase;
    setAiPhase(phase);
  }, [phase]);

  // Cleanup on unmount
  useEffect(() => () => {
    listenRef.current?.stop();
    abortStreamRef.current?.();
    wakeRef.current?.stop();
    stopSpeaking();
  }, []);

  const submitToBackend = useCallback((finalUserText: string) => {
    setPhase('thinking');
    setAssistantText('');
    let assistantBuf = '';

    abortStreamRef.current = streamChat(
      {
        messages: [{ role: 'user', content: finalUserText }],
        conversationId: convId ?? undefined,
        maxNewTokens: 600,
      },
      {
        onMeta: (cid) => {
          if (!convId) setConvId(cid);
        },
        onToken: (text) => {
          assistantBuf += text;
          // Strip live tool tags to keep the caption clean.
          const visible = assistantBuf
            .replace(/\[\s*(?:[A-Z_]+\s*:?\s*)?[a-z_]+\b[^\]]*?\]/gi, '')
            .replace(/\n{3,}/g, '\n\n')
            .trim();
          setAssistantText(visible);
        },
        onRevision: (text) => setAssistantText(text),
        onDone: () => {
          // Final clean-up + speak
          const final = assistantBuf
            .replace(/\[\s*(?:[A-Z_]+\s*:?\s*)?[a-z_]+\b[^\]]*?\]/gi, '')
            .replace(/\n{3,}/g, '\n\n')
            .trim();
          setAssistantText(final);
          if (opts.autoSpeak && ttsOk && final) {
            setLastAssistantSpeak(final);
            setPhase('speaking');
            speak(final, {
              lang: 'it',
              onEnd: () => setPhase('idle'),
            });
          } else {
            setPhase('idle');
          }
          abortStreamRef.current = null;
        },
        onError: (detail) => {
          setAssistantText(`⚠️ ${detail}`);
          setPhase('idle');
          abortStreamRef.current = null;
        },
      },
    );
  }, [convId, opts.autoSpeak, ttsOk]);

  const start = useCallback(() => {
    logVoice('start() called', { phase, sttOk, ttsOk, interim: interimRef.current });
    if (phase === 'speaking') {
      // Tap during TTS = stop talking, return to idle (interrupt CARA).
      stopSpeaking();
      setPhase('idle');
      return;
    }
    if (phase === 'listening') {
      // Tap during listen = STOP + submit whatever we've heard so far.
      // Two cases: browser SR (interim ref) or whisper fallback (record).
      if (whisperRef.current) {
        const handle = whisperRef.current;
        whisperRef.current = null;
        submittedRef.current = true;
        setPhase('thinking');   // upload + transcribe takes 1-3 s on RK3588
        handle
          .stop()
          .then((text) => {
            const captured = (text || '').trim();
            logVoice('whisper transcribed', { captured });
            if (captured) {
              setUserText(captured);
              submitToBackend(captured);
            } else {
              setPhase('idle');
            }
          })
          .catch((e: Error) => {
            logVoice('whisper transcribe failed', e);
            setErrorMessage(`Trascrizione fallita: ${e.message}`);
            setPhase('idle');
          });
        return;
      }
      // Browser SR path — use interimRef (always-current) instead of
      // waiting for an `isFinal` event that may never come.
      const handle = listenRef.current;
      listenRef.current = null;
      handle?.stop();
      const captured = interimRef.current.trim();
      logVoice('tap-during-listening', { captured });
      submittedRef.current = true;   // tell onEnd not to re-submit
      if (captured) {
        submitToBackend(captured);
      } else {
        // Nothing said: cancel cleanly.
        setPhase('idle');
      }
      return;
    }
    if (phase === 'thinking') {
      // Cancel in-flight thinking.
      abortStreamRef.current?.();
      abortStreamRef.current = null;
      setPhase('idle');
      return;
    }
    // idle → start listening. Two paths:
    //   (a) browser SR is available → use it (fast, low-latency interim)
    //   (b) no SR but MediaRecorder available → record + upload to whisper
    if (!sttOk) {
      if (!whisperRecorderAvailable()) {
        setErrorMessage(
          'Riconoscimento vocale non supportato in questo browser. Apri /chat per scrivere.',
        );
        return;
      }
      // Whisper fallback path — record until next tap.
      logVoice('starting whisper fallback recording');
      setErrorMessage(null);
      setUserText('');
      setAssistantText('');
      interimRef.current = '';
      submittedRef.current = false;
      setPhase('listening');
      startWhisperRecording({ language: 'it', maxDurationMs: 30_000 })
        .then((handle) => {
          whisperRef.current = handle;
        })
        .catch((e: Error) => {
          logVoice('whisper recording failed to start', e);
          setErrorMessage(`Microfono non avviato: ${e.message}`);
          setPhase('idle');
        });
      return;
    }
    // Pause the wake-word listener SYNCHRONOUSLY before we ask for the mic
    // so the two recognizers don't fight over the same audio stream.
    if (wakeRef.current) {
      logVoice('pausing wake-word before conversational STT');
      wakeRef.current.pause();
    }
    setErrorMessage(null);
    setUserText('');
    setAssistantText('');
    interimRef.current = '';
    submittedRef.current = false;
    setPhase('listening');
    // 400 ms debounce after isFinal: iOS sometimes emits a shorter "che
    // ore" final, then a longer "che ore sono" final within the same
    // session. We hold the submit briefly to keep the longer transcript.
    let finalTimer: ReturnType<typeof setTimeout> | null = null;
    let handle: ListenHandle | null = null;
    try {
      handle = startListening({
        lang: 'it',
        interim: true,
        // continuous=false: works reliably on iOS Safari (the alternative
        // path made it silent). We now lean on:
        //  - interimRef populated on every onText so we never lose a partial
        //  - tap-to-submit when the user re-presses the mic mid-listen
        //  - onEnd fallback that submits interim if no isFinal arrived
        continuous: false,
        onText: (text, isFinal) => {
          interimRef.current = text;
          setUserText(text);
          if (isFinal && text.trim() && !submittedRef.current) {
            if (finalTimer) clearTimeout(finalTimer);
            finalTimer = setTimeout(() => {
              if (submittedRef.current) return;
              submittedRef.current = true;
              listenRef.current = null;
              try {
                handle?.stop();
              } catch {
                /* already stopping */
              }
              // Use whatever interim accumulated during the debounce
              // (it'll be either the original `text` or a longer
              // follow-up that arrived inside the 400 ms window).
              const finalText = (interimRef.current || text).trim();
              submitToBackend(finalText);
            }, 400);
          }
        },
        onEnd: () => {
          logVoice('STT onEnd', { submitted: submittedRef.current, interim: interimRef.current });
          listenRef.current = null;
          if (submittedRef.current) {
            // already submitted by tap or isFinal; nothing to do
            return;
          }
          // No isFinal arrived (iOS pause / silence timeout). If we have ANY
          // interim text, give the engine a moment to maybe deliver an
          // isFinal — then submit anyway so the user's question isn't lost.
          const captured = interimRef.current.trim();
          if (captured) {
            submittedRef.current = true;
            window.setTimeout(() => submitToBackend(captured), 300);
          } else {
            setPhase((prev) => (prev === 'listening' ? 'idle' : prev));
          }
        },
        onError: (err) => {
          logVoice('STT onError', err);
          listenRef.current = null;
          const msg = describeMicError(err);
          if (msg) setErrorMessage(msg);
          setPhase('idle');
        },
      });
    } catch (e) {
      logVoice('startListening threw', e);
      setErrorMessage(`Microfono non avviato: ${(e as Error).message}`);
      setPhase('idle');
      return;
    }
    if (handle === null) {
      logVoice('startListening returned null (no recognizer)');
      setErrorMessage(
        'Riconoscimento vocale non disponibile. Apri /chat per scrivere.',
      );
      setPhase('idle');
      return;
    }
    listenRef.current = handle;
  }, [phase, sttOk, ttsOk, submitToBackend]);

  const stop = useCallback(() => {
    listenRef.current?.stop();
    listenRef.current = null;
    abortStreamRef.current?.();
    abortStreamRef.current = null;
    stopSpeaking();
    setPhase('idle');
  }, []);

  const cancel = stop;

  // Wake-word lifecycle. The wake-word recognizer and the conversational STT
  // both fight for the same microphone, so we mount the listener once and
  // pause/resume it based on the conversation phase.
  useEffect(() => {
    if (!opts.wakeWord || !sttOk) {
      // If the option flips off mid-session, stop any running listener.
      if (wakeRef.current) {
        wakeRef.current.stop();
        wakeRef.current = null;
        setWakeWordActive(false);
      }
      return;
    }
    wakeRef.current = startWakeWord({
      onWake: (followUp) => {
        // If the wake word was followed by a question in the same utterance,
        // submit it directly. Otherwise, start a fresh conversational turn.
        if (followUp && followUp.trim()) {
          setUserText(followUp);
          setAssistantText('');
          submitToBackend(followUp);
        } else {
          // Small delay so the browser releases the mic from the wake-word
          // recognizer before we open a new one for conversational STT.
          setTimeout(() => {
            if (phaseRef.current === 'idle') start();
          }, 250);
        }
      },
    });
    setWakeWordActive(wakeRef.current !== null);
    return () => {
      wakeRef.current?.stop();
      wakeRef.current = null;
      setWakeWordActive(false);
    };
  }, [opts.wakeWord, sttOk, submitToBackend, start]);

  // Pause the passive wake-word listener whenever we're actively in a
  // conversation (the mic can only do one thing at a time).
  useEffect(() => {
    if (!wakeRef.current) return;
    if (phase === 'idle') {
      wakeRef.current.resume();
    } else {
      wakeRef.current.pause();
    }
  }, [phase]);

  return {
    phase,
    userText,
    assistantText,
    lastAssistantSpeak,
    start,
    stop,
    cancel,
    ttsOk,
    sttOk,
    wakeWordActive,
    errorMessage,
    dismissError,
  };
}
