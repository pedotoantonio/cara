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

/**
 * Pick the STT path. On mobile (iOS, Android) and inside an installed PWA
 * the browser's `SpeechRecognition` is unreliable: iOS Safari often
 * silently refuses to fire `onresult` from a standalone PWA, Android
 * Chrome installed-PWA loses the recognizer when the SW takes over the
 * mic. Server-side Whisper via MediaRecorder is far more reliable on
 * those platforms (and works offline-from-Google because it's local).
 *
 * Returns true when we should use Whisper FIRST, falling back to native
 * SR only when MediaRecorder isn't available.
 */
function preferWhisperStt(): boolean {
  if (typeof window === 'undefined') return false;
  if (!whisperRecorderAvailable()) return false;
  const ua = navigator.userAgent || '';
  const isIOS = /iPad|iPhone|iPod/.test(ua);
  if (isIOS) return true;
  const isAndroid = /Android/.test(ua);
  // PWA standalone — both display-mode media query and the iOS-specific
  // `navigator.standalone` flag.
  const isStandalone =
    window.matchMedia?.('(display-mode: standalone)').matches ||
    Boolean((window.navigator as { standalone?: boolean }).standalone);
  if (isAndroid && isStandalone) return true;
  // Touch device with no native SR → only path is whisper.
  if (!sttAvailable()) return true;
  return false;
}
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
  /** Live mic level in dBFS (-60..0). -60 outside listening. */
  micDb: number;
  /** Normalised 0..1 mic level. 0 outside listening. */
  micLevel: number;
  /** True if the mic pipeline meter is active for this session. */
  meterActive: boolean;
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
  // Live mic level — refs hold the latest value so we don't trigger a
  // setState every animation frame; a single setState pump at ~20 Hz
  // keeps React renders cheap while the bar still feels live.
  const micDbRef = useRef<number>(-60);
  const micLevelRef = useRef<number>(0);
  const [micDb, setMicDb] = useState<number>(-60);
  const [micLevel, setMicLevel] = useState<number>(0);
  const [meterActive, setMeterActive] = useState<boolean>(false);
  const meterPumpRef = useRef<number | null>(null);

  function _startMeterPump() {
    if (meterPumpRef.current !== null) return;
    const tick = () => {
      setMicDb(micDbRef.current);
      setMicLevel(micLevelRef.current);
      meterPumpRef.current = window.setTimeout(tick, 50);
    };
    setMeterActive(true);
    tick();
  }

  function _stopMeterPump() {
    if (meterPumpRef.current !== null) {
      clearTimeout(meterPumpRef.current);
      meterPumpRef.current = null;
    }
    setMeterActive(false);
    setMicDb(-60);
    setMicLevel(0);
    micDbRef.current = -60;
    micLevelRef.current = 0;
  }

  function _whisperOpts() {
    return {
      language: 'it',
      maxDurationMs: 30_000,
      vadMode: 'auto' as const,
      onLevel: (db: number, lvl: number) => {
        micDbRef.current = db;
        micLevelRef.current = lvl;
      },
      onAutoStop: () => {
        // VAD decided we're done — go straight to thinking and pull
        // the transcript via the same path the manual tap-stop uses.
        if (!whisperRef.current) return;
        const handle = whisperRef.current;
        whisperRef.current = null;
        submittedRef.current = true;
        setPhase('thinking');
        _stopMeterPump();
        handle.stopWithDiag()
          .then((r) => _handleWhisperResult(r))
          .catch((e: Error) => {
            logVoice('whisper auto-stop transcribe failed', e);
            setErrorMessage(`Trascrizione fallita: ${e.message}`);
            setPhase('idle');
          });
      },
    };
  }

  function _handleWhisperResult(r: {
    text: string;
    failureHint?: string | null;
    confidence?: string;
  }) {
    const captured = (r.text || '').trim();
    logVoice('whisper transcribed', { captured, confidence: r.confidence });
    if (captured && (r.confidence === 'high' || r.confidence === 'medium' || !r.confidence)) {
      setUserText(captured);
      submitToBackend(captured);
      return;
    }
    // Empty OR low-confidence: never silent. Surface the precise hint
    // returned by the mic pipeline (it knows whether the user was
    // muted, too quiet, or whisper just couldn't decode).
    setErrorMessage(r.failureHint || 'Non ho capito. Riprova.');
    setPhase('idle');
  }
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
    whisperRef.current?.abort();
    stopSpeaking();
    if (meterPumpRef.current !== null) {
      clearTimeout(meterPumpRef.current);
      meterPumpRef.current = null;
    }
    void import('./streamingAudio').then(({ clear }) => clear());
  }, []);

  const submitToBackend = useCallback((finalUserText: string) => {
    setPhase('thinking');
    setAssistantText('');
    let assistantBuf = '';
    // Track sentence-streamed audio chunks; if any arrive, skip the
    // legacy speak(final) on done — playback is already happening.
    let streamedAudioChunks = 0;

    // Lazy-import the streaming queue so non-voice routes don't pull
    // the WebAudio code into their initial bundle.
    void import('./streamingAudio').then(({ startTurn }) => {
      startTurn(() => setPhase('idle'));
    });

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
          const visible = assistantBuf
            .replace(/\[\s*(?:[A-Z_]+\s*:?\s*)?[a-z_]+\b[^\]]*?\]/gi, '')
            .replace(/\n{3,}/g, '\n\n')
            .trim();
          setAssistantText(visible);
        },
        onAudioChunk: (chunk) => {
          streamedAudioChunks += 1;
          // First chunk → flip phase to speaking so the avatar lip-sync
          // and caption switch over to the assistant text.
          if (streamedAudioChunks === 1) setPhase('speaking');
          void import('./streamingAudio').then(({ enqueueAudioChunk }) => {
            enqueueAudioChunk(chunk.audio_b64, {
              seq: chunk.seq, text: chunk.text, voiceId: chunk.voice_id,
            });
          });
        },
        onRevision: (text) => setAssistantText(text),
        onDone: () => {
          const final = assistantBuf
            .replace(/\[\s*(?:[A-Z_]+\s*:?\s*)?[a-z_]+\b[^\]]*?\]/gi, '')
            .replace(/\n{3,}/g, '\n\n')
            .trim();
          setAssistantText(final);

          if (streamedAudioChunks > 0) {
            // Audio is already playing. Tell the queue this is the last
            // chunk so it can call onAllDone (→ phase='idle') when the
            // last buffer finishes.
            void import('./streamingAudio').then(({ endTurn }) => endTurn());
            setLastAssistantSpeak(final);
          } else if (opts.autoSpeak && ttsOk && final) {
            // Backend didn't stream audio (admin flag off or browser
            // voice mode) — fall back to single-shot speak().
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
      void import('./streamingAudio').then(({ clear }) => clear());
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
        _stopMeterPump();
        handle
          .stopWithDiag()
          .then((r) => _handleWhisperResult(r))
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
    // idle → start listening. Three branches in priority:
    //   (1) preferWhisperStt() → record + upload to whisper (mobile, iOS,
    //       Android PWA standalone, or browsers without native SR)
    //   (2) sttAvailable() → use the browser SR (low-latency interim,
    //       desktop Chrome / Edge)
    //   (3) no path available → show actionable error
    if (preferWhisperStt()) {
      logVoice('starting whisper recording (preferred for this platform)');
      setErrorMessage(null);
      setUserText('');
      setAssistantText('');
      interimRef.current = '';
      submittedRef.current = false;
      setPhase('listening');
      _startMeterPump();
      startWhisperRecording(_whisperOpts())
        .then((handle) => {
          whisperRef.current = handle;
        })
        .catch((e: Error) => {
          _stopMeterPump();
          logVoice('whisper recording failed to start', e);
          // Map common getUserMedia errors to user-friendly Italian.
          let msg = `Microfono non avviato: ${e.message}`;
          const m = (e.message || '').toLowerCase();
          if (m.includes('notallowederror') || m.includes('permission')) {
            msg = 'Permesso microfono negato. Vai nelle impostazioni del browser e abilita il microfono per CARA, poi riprova.';
          } else if (m.includes('notfounderror') || m.includes('devicenot')) {
            msg = 'Nessun microfono rilevato sul dispositivo.';
          } else if (m.includes('notreadable') || m.includes('aborterror')) {
            msg = 'Il microfono è già usato da un\'altra app. Chiudi quella e riprova.';
          }
          setErrorMessage(msg);
          setPhase('idle');
        });
      return;
    }
    if (!sttAvailable()) {
      // No native SR and whisper unavailable too (no MediaRecorder).
      setErrorMessage(
        'Riconoscimento vocale non disponibile in questo browser. Apri /chat per scrivere a CARA.',
      );
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
          const isNetworkErr = err.toLowerCase().includes('network');
          // On `network` errors (Web Speech uses Google STT which needs the
          // public internet) fall back to local Whisper if available — the
          // backend ASR lives on LAN so it works even when the device has
          // no usable Google connectivity.
          if (isNetworkErr && whisperRecorderAvailable()) {
            logVoice('STT network error → falling back to Whisper recording');
            setUserText('');
            interimRef.current = '';
            submittedRef.current = false;
            setPhase('listening');
            _startMeterPump();
            startWhisperRecording(_whisperOpts())
              .then((h) => { whisperRef.current = h; })
              .catch((e: Error) => {
                _stopMeterPump();
                logVoice('whisper fallback also failed', e);
                setErrorMessage(`Microfono non avviato: ${e.message}`);
                setPhase('idle');
              });
            return;
          }
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
    whisperRef.current?.abort();
    whisperRef.current = null;
    abortStreamRef.current?.();
    abortStreamRef.current = null;
    stopSpeaking();
    _stopMeterPump();
    setPhase('idle');
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    micDb,
    micLevel,
    meterActive,
  };
}
