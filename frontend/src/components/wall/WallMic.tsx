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

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const armedAtRef = useRef<number>(0);
  const wakeRecRef = useRef<SpeechRecognitionLike | null>(null);
  const phaseRef = useRef<Phase>('idle');

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  // Quick capability probes for the diagnostics tooltip.
  const supportsMR =
    typeof window !== 'undefined' &&
    typeof window.MediaRecorder !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia;
  const supportsWake = Boolean(getRecognitionCtor());

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
    rec.lang = 'it-IT';
    rec.continuous = true;
    rec.interimResults = false;
    rec.onresult = (ev) => {
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
      if (code !== 'no-speech' && code !== 'aborted') {
        setDiag(`wake: ${code}`);
      }
    };
    rec.onend = () => {
      // Auto-restart so the listener keeps running.
      if (wakeRecRef.current === rec && phaseRef.current !== 'speaking') {
        try { rec.start(); } catch { /* noop */ }
      }
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
    try {
      recorderRef.current?.stop();
    } catch { /* noop */ }
    recorderRef.current = null;
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
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
    chunksRef.current = [];
    armedAtRef.current = Date.now();

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 48000,
          noiseSuppression: true,
          echoCancellation: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;
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
      return;
    }

    let rec: MediaRecorder;
    try {
      // Prefer Opus in WebM. Whisper handles it via ffmpeg.
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/webm')
          ? 'audio/webm'
          : '';
      rec = mime
        ? new MediaRecorder(streamRef.current, { mimeType: mime, audioBitsPerSecond: 64_000 })
        : new MediaRecorder(streamRef.current);
    } catch (e) {
      setDiag(`Recorder non avviato: ${(e as Error).message}`);
      setPhase('error');
      stopAll();
      window.setTimeout(() => setPhase('idle'), 3500);
      return;
    }

    rec.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) chunksRef.current.push(ev.data);
    };
    rec.onstop = async () => {
      // Stop the underlying tracks so the mic indicator goes away.
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
      const elapsed = Date.now() - armedAtRef.current;
      const blob = new Blob(chunksRef.current, { type: rec.mimeType || 'audio/webm' });
      chunksRef.current = [];
      // Too short → user just tapped, ignore.
      if (elapsed < 400 || blob.size < 1500) {
        setPhase('idle');
        return;
      }
      await uploadAndAsk(blob);
    };

    recorderRef.current = rec;
    rec.start(500); // emit chunks every 500ms so onstop has data fast
    setPhase('listening');
  }

  function stopRecording() {
    const rec = recorderRef.current;
    if (rec && rec.state !== 'inactive') {
      try { rec.stop(); } catch { /* noop */ }
    }
  }

  async function uploadAndAsk(blob: Blob) {
    setPhase('transcribing');
    let text = '';
    try {
      text = await transcribeAudio(blob, 'it');
    } catch (e) {
      setDiag(`ASR fallita: ${(e as Error).message}`);
      setPhase('error');
      window.setTimeout(() => setPhase('idle'), 3500);
      return;
    }
    if (!text) {
      setDiag('Non ho capito, riprova più vicino al microfono');
      setPhase('error');
      window.setTimeout(() => setPhase('idle'), 2500);
      return;
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
          if (phase === 'listening') stopRecording();
        }}
        onPointerCancel={() => { if (phase === 'listening') stopRecording(); }}
        onPointerLeave={() => { if (phase === 'listening') stopRecording(); }}
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
      {/* Single-line transcript track. Always reserves vertical space
          (h-7) so layout doesn't jump when text appears. Inline-flow,
          not absolute-positioned, so it never overlaps siblings. */}
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
