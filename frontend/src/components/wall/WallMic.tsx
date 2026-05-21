// Voice button for the Wall — push-to-talk.
//
// We default to MediaRecorder + backend Whisper (`/api/v1/wall/asr`)
// because Web Speech (Chrome's `webkitSpeechRecognition`) requires
// internet, varies per browser, and silently fails on Firefox /
// Safari and on some kiosk Chromiums. MediaRecorder is universally
// supported once microphone permission is granted, and Whisper runs
// on-box.
//
// Push-to-talk: pointer-down arms the recorder, pointer-up stops it
// and uploads the blob. After a transcript comes back we POST to
// `/wall/ask` and play the Piper WAV reply.

import { useEffect, useRef, useState } from 'react';

import { askCara, transcribeAudio } from '../../api/wall';
import { AudioLevelMeter } from '../AudioLevelMeter';
import {
  diagnoseMicFailure,
  startMicSession,
  type MicSession,
} from '../../lib/micPipeline';

type Phase = 'idle' | 'listening' | 'transcribing' | 'thinking' | 'speaking' | 'error';

// We type the constructor loosely so TS doesn't complain — the real
// API is provided by the browser when available.
type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((ev: { results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((ev: { error?: string }) => void) | null;
};

declare global {
  interface Window {
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
    SpeechRecognition?: new () => SpeechRecognitionLike;
  }
}

function getRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === 'undefined') return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

export function WallMic() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [transcript, setTranscript] = useState<string>('');
  const [reply, setReply] = useState<string>('');
  const [diag, setDiag] = useState<string>('');
  // Wake-word listener state. When true, we keep a passive
  // SpeechRecognition session listening for "cara"; on detection we
  // auto-start the MediaRecorder pipeline.
  const [wakeOn, setWakeOn] = useState<boolean>(false);

  const sessionRef = useRef<MicSession | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const wakeRecRef = useRef<SpeechRecognitionLike | null>(null);
  const phaseRef = useRef<Phase>('idle');
  // Live mic level — refs hold the latest value, a 50ms pump mirrors
  // to state so the bar renders smoothly without flooding React.
  const micDbRef = useRef<number>(-60);
  const micLevelRef = useRef<number>(0);
  const [micDb, setMicDb] = useState<number>(-60);
  const [micLevel, setMicLevel] = useState<number>(0);
  const meterPumpRef = useRef<number | null>(null);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  // Quick capability probes for the diagnostics tooltip.
  const supportsMR =
    typeof window !== 'undefined' &&
    typeof window.MediaRecorder !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia;
  const supportsWake = Boolean(getRecognitionCtor());

  function _startMeterPump() {
    if (meterPumpRef.current !== null) return;
    const tick = () => {
      setMicDb(micDbRef.current);
      setMicLevel(micLevelRef.current);
      meterPumpRef.current = window.setTimeout(tick, 50);
    };
    tick();
  }

  function _stopMeterPump() {
    if (meterPumpRef.current !== null) {
      clearTimeout(meterPumpRef.current);
      meterPumpRef.current = null;
    }
    setMicDb(-60);
    setMicLevel(0);
    micDbRef.current = -60;
    micLevelRef.current = 0;
  }

  useEffect(() => {
    return () => {
      stopAll();
      stopWake();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Mount/unmount the wake-word listener when the toggle flips. We
  // restart the recognizer on each `onend` so it stays alive as long
  // as `wakeOn` is true (browsers terminate the session after every
  // utterance).
  useEffect(() => {
    if (!wakeOn) {
      stopWake();
      return;
    }
    if (!supportsWake) return;
    startWake();
    return () => stopWake();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wakeOn]);

  function startWake() {
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;
    if (wakeRecRef.current) return;
    let rec: SpeechRecognitionLike;
    try {
      rec = new Ctor();
    } catch {
      return;
    }
    // Track consecutive errors so we throttle restarts instead of hammering
    // the API when the network to Google STT is wobbling.
    let wakeErrCount = 0;
    let wakeRestartTimer: ReturnType<typeof setTimeout> | null = null;
    const WAKE_BACKOFF_MS = [400, 2_000, 5_000, 15_000, 60_000];
    rec.lang = 'it-IT';
    rec.continuous = true;
    rec.interimResults = false;
    rec.onresult = (ev) => {
      // Got a transcript → connection to STT is healthy; reset backoff.
      wakeErrCount = 0;
      // Look for "cara" in any final result. The user can be saying
      // anything around it — "cara accendi…", "ehi cara…", etc.
      // Conservative: only trigger when the recorder is idle and not
      // already speaking back.
      const results = ev.results;
      for (let i = 0; i < results.length; i++) {
        const text = results[i][0]?.transcript?.toLowerCase() || '';
        if (results[i].isFinal && /\bcara\b/.test(text)) {
          if (phaseRef.current === 'idle' || phaseRef.current === 'error') {
            setDiag('Parola d\'ordine "CARA" rilevata');
            void startRecording();
          }
          return;
        }
      }
    };
    rec.onerror = (ev) => {
      const code = ev.error || 'unknown';
      // `no-speech`/`aborted` are normal — recognition restarts in onend.
      // `network` happens whenever Chrome can't reach Google STT (transient
      // ISP hiccup, DNS lag, captive portal). Surface NOTHING for it —
      // it's actionable only by the network, not by the user, and showing
      // a toast every few seconds is just noise.
      if (code !== 'no-speech' && code !== 'aborted' && code !== 'network') {
        setDiag(`wake: ${code}`);
      }
      if (code !== 'no-speech' && code !== 'aborted') {
        wakeErrCount += 1;
      }
    };
    rec.onend = () => {
      // Auto-restart so the listener keeps running, but back off on error
      // streaks so a flaky network doesn't burn battery + CPU in a loop.
      if (wakeRecRef.current !== rec || phaseRef.current === 'speaking') return;
      const idx = Math.min(wakeErrCount, WAKE_BACKOFF_MS.length - 1);
      const delay = wakeErrCount === 0 ? 0 : WAKE_BACKOFF_MS[idx];
      if (wakeRestartTimer) clearTimeout(wakeRestartTimer);
      wakeRestartTimer = setTimeout(() => {
        if (wakeRecRef.current !== rec) return;
        try {
          rec.start();
          // A successful start resets the error counter on next onresult.
        } catch { /* noop */ }
      }, delay);
    };
    try {
      rec.start();
      wakeRecRef.current = rec;
    } catch {
      wakeRecRef.current = null;
    }
  }

  function stopWake() {
    if (wakeRecRef.current) {
      try { wakeRecRef.current.abort(); } catch { /* noop */ }
      wakeRecRef.current = null;
    }
  }

  function stopAll() {
    sessionRef.current?.abort();
    sessionRef.current = null;
    _stopMeterPump();
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
  }

  async function startRecording() {
    if (!supportsMR) {
      setDiag('MediaRecorder non disponibile in questo browser');
      setPhase('error');
      window.setTimeout(() => setPhase('idle'), 3000);
      return;
    }
    setReply('');
    setTranscript('');
    setDiag('');

    try {
      const session = await startMicSession({
        // Push-to-talk on the Wall = manual stop only. VAD would
        // betray user expectations ("ho ancora il dito sopra!").
        vadMode: 'manual',
        maxDurationMs: 30_000,
        onLevel: (db, lvl) => {
          micDbRef.current = db;
          micLevelRef.current = lvl;
        },
      });
      sessionRef.current = session;
      _startMeterPump();
      setPhase('listening');
    } catch (e) {
      const err = e as DOMException;
      const msg = err?.name === 'NotAllowedError'
        ? 'Permesso microfono negato'
        : err?.name === 'NotFoundError'
          ? 'Nessun microfono trovato'
          : `Errore microfono: ${err?.message || err?.name || 'unknown'}`;
      setDiag(msg);
      setPhase('error');
      window.setTimeout(() => setPhase('idle'), 3500);
    }
  }

  async function stopRecording() {
    const session = sessionRef.current;
    if (!session) return;
    sessionRef.current = null;
    setPhase('transcribing');
    let result: { blob: Blob; diag: ReturnType<typeof session.getDiag> };
    try {
      result = await session.stop();
    } catch {
      _stopMeterPump();
      setPhase('idle');
      return;
    }
    _stopMeterPump();
    const { blob, diag } = result;
    // Too short → user just tapped accidentally, ignore.
    if (diag.recordedMs < 400 || blob.size < 1500) {
      setPhase('idle');
      return;
    }
    await uploadAndAsk(blob, diag);
  }

  async function uploadAndAsk(
    blob: Blob,
    micDiag: ReturnType<MicSession['getDiag']>,
  ) {
    let asr: Awaited<ReturnType<typeof transcribeAudio>>;
    try {
      asr = await transcribeAudio(blob, 'it');
    } catch (e) {
      setDiag(`ASR fallita: ${(e as Error).message}`);
      setPhase('error');
      window.setTimeout(() => setPhase('idle'), 3500);
      return;
    }
    const text = (asr.text || '').trim();
    const hint = diagnoseMicFailure(micDiag, text, asr.confidence_label);
    if (!text) {
      // Empty transcript — never silent. Show the precise mic
      // pipeline hint instead of a generic "non ho capito".
      setDiag(hint || 'Non ho capito, riprova');
      setPhase('error');
      window.setTimeout(() => setPhase('idle'), 6000);
      return;
    }
    if (asr.confidence_label === 'low' && hint) {
      // Low confidence — show what we heard but let the user retry.
      setTranscript(text);
      setDiag(hint);
    }
    setTranscript(text);
    setPhase('thinking');
    try {
      const out = await askCara(text, true);
      setReply(out.text);
      if (out.audio_base64 && out.audio_mime) {
        const audioBlob = b64ToBlob(out.audio_base64, out.audio_mime);
        const url = URL.createObjectURL(audioBlob);
        const a = new Audio(url);
        audioRef.current = a;
        setPhase('speaking');
        a.onended = () => {
          URL.revokeObjectURL(url);
          setPhase('idle');
          window.setTimeout(() => {
            setTranscript('');
            setReply('');
          }, 6000);
        };
        a.onerror = () => {
          URL.revokeObjectURL(url);
          setPhase('idle');
        };
        await a.play().catch(() => setPhase('idle'));
      } else {
        setPhase('idle');
      }
    } catch (e) {
      setDiag(`Errore CARA: ${(e as Error).message}`);
      setPhase('error');
      window.setTimeout(() => setPhase('idle'), 3000);
    }
  }

  if (!supportsMR) {
    return (
      <div className="text-fg-muted text-xs italic">
        Microfono non supportato su questo browser
      </div>
    );
  }

  const buttonLabel = (() => {
    switch (phase) {
      case 'listening': return 'In ascolto…';
      case 'transcribing': return 'Trascrizione…';
      case 'thinking': return 'CARA pensa…';
      case 'speaking': return 'CARA parla';
      case 'error': return diag || 'Errore';
      default: return 'Tieni premuto per parlare';
    }
  })();

  const ringColor = (() => {
    switch (phase) {
      case 'listening': return 'ring-rose-500';
      case 'transcribing': return 'ring-amber-500';
      case 'thinking': return 'ring-amber-500';
      case 'speaking': return 'ring-emerald-500';
      case 'error': return 'ring-alert';
      default: return 'ring-accent/50';
    }
  })();

  // Build a single-line transcript string. We avoid two separate
  // <div>s because the user wants ONE horizontal line, not stacked
  // lines. When both transcript and reply exist we join them with a
  // separator. The marquee scrolls only when the text overflows the
  // fixed-width track.
  const lineText = (() => {
    const parts: string[] = [];
    if (transcript) parts.push(`« ${transcript} »`);
    if (reply) parts.push(reply);
    return parts.join('   →   ');
  })();

  return (
    <div className="flex flex-col items-center gap-2 select-none">
      <button
        type="button"
        onPointerDown={(e) => {
          e.preventDefault();
          if (phase === 'idle' || phase === 'error') void startRecording();
        }}
        onPointerUp={(e) => {
          e.preventDefault();
          if (phase === 'listening') void stopRecording();
        }}
        onPointerCancel={() => { if (phase === 'listening') void stopRecording(); }}
        onPointerLeave={() => { if (phase === 'listening') void stopRecording(); }}
        className={[
          'inline-flex items-center justify-center rounded-full',
          'w-16 h-16 bg-bg/60 backdrop-blur-sm transition-all',
          'ring-4', ringColor,
          phase === 'listening' ? 'scale-110 animate-pulse' : '',
          phase === 'thinking' || phase === 'speaking' || phase === 'transcribing'
            ? 'opacity-90' : '',
          'touch-none',
        ].join(' ')}
        aria-label={buttonLabel}
        title={buttonLabel}
        disabled={phase === 'transcribing' || phase === 'thinking'}
      >
        <span style={{ fontSize: 28 }}>
          {phase === 'speaking'
            ? '🔊'
            : phase === 'thinking' || phase === 'transcribing'
              ? '⏳'
              : '🎤'}
        </span>
      </button>
      <span
        className="text-fg-soft text-center whitespace-nowrap"
        style={{ fontSize: 'clamp(11px, 0.9vw, 14px)' }}
      >
        {buttonLabel}
      </span>
      {/* Live mic level meter — only while actively recording. */}
      <AudioLevelMeter
        active={phase === 'listening'}
        db={micDb}
        level={micLevel}
        width={224}
      />
      {/* Single-line transcript track. */}
      <MicTranscriptLine text={lineText} />
      {supportsWake && (
        <button
          type="button"
          onClick={() => setWakeOn((v) => !v)}
          className={[
            'inline-flex items-center gap-1.5 rounded-pill px-3 py-1 text-xs',
            wakeOn
              ? 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-300'
              : 'bg-surface2/80 text-fg-muted hover:text-fg',
          ].join(' ')}
          title={wakeOn
            ? 'Wake-word "CARA" attiva: di "CARA" + comando'
            : 'Attiva wake-word: dì "CARA" per parlare senza premere'}
        >
          {wakeOn && (
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
          )}
          {wakeOn ? 'Wake "CARA" attivo' : 'Attiva wake "CARA"'}
        </button>
      )}
    </div>
  );
}

function MicTranscriptLine({ text }: { text: string }) {
  if (!text) {
    return <div className="h-7" aria-hidden="true" />;
  }
  // Heuristic: text wider than ~30 chars likely needs scrolling. We
  // duplicate the string and animate the inner track so the loop is
  // seamless.
  const needsScroll = text.length > 30;
  return (
    <div
      className="w-72 max-w-[60vw] h-7 overflow-hidden rounded-full bg-bg/85 backdrop-blur-sm flex items-center px-3"
      style={{ fontSize: 'clamp(12px, 1vw, 15px)' }}
      aria-live="polite"
    >
      {needsScroll ? (
        <div className="flex whitespace-nowrap animate-marquee-x">
          <span className="text-fg pr-12">{text}</span>
          <span className="text-fg pr-12" aria-hidden="true">{text}</span>
        </div>
      ) : (
        <span className="text-fg whitespace-nowrap mx-auto">{text}</span>
      )}
    </div>
  );
}

function b64ToBlob(b64: string, mime: string): Blob {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}
