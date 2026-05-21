/**
 * Mic pipeline — recording + live audio level meter + VAD auto-stop.
 *
 * Wraps MediaRecorder with a Web Audio AnalyserNode so we can:
 *
 *   1. Show a LIVE level meter to the user (otherwise they have no
 *      idea whether CARA is actually hearing them or the OS muted the
 *      mic — the #1 cause of "rimane in attesa ma non capisce nulla").
 *   2. Auto-stop on silence (VAD) — record while voice present, stop
 *      after 1.2 s of silence post-speech. The user doesn't have to
 *      tap-stop.
 *   3. Calibrate the noise floor in the first 300 ms so the speech
 *      threshold adapts to a noisy room vs a quiet one.
 *   4. Surface diagnostics (max dB, voice ms, silence tail ms, blob
 *      bytes) so when ASR returns "" the UI knows WHY.
 *
 * Why no library: Web Audio API is universal, ~100 LOC of math, zero
 * deps, zero npm churn. Faster-whisper is on the backend.
 */

export interface MicPipelineOptions {
  /** Hard cap on recording duration in ms (default 30 s). */
  maxDurationMs?: number;
  /**
   * VAD mode:
   *  - 'auto'   (default) — auto-stop on silence after speech detected.
   *  - 'manual' — wait for explicit stop(); push-to-talk on the Wall.
   */
  vadMode?: 'auto' | 'manual';
  /**
   * Minimum voiced duration (ms) before auto-stop is allowed. Prevents
   * cutting off a slow speaker who pauses to think. Default 600 ms.
   */
  minVoiceMs?: number;
  /**
   * Silence tail (ms) after voice that triggers auto-stop. Default 1200.
   * Too short → cuts mid-sentence; too long → user thinks it's broken.
   */
  silenceTailMs?: number;
  /**
   * Called every animation frame (~60 Hz) with the current dBFS level
   * and a normalised 0..1 value. Drives the live level meter UI.
   * Important: this fires hot, do NOT React-setState directly here in
   * hot paths — clamp via requestAnimationFrame on the consumer side.
   */
  onLevel?: (db: number, normalised: number) => void;
  /**
   * Called once when speech is first detected (transitions silent→voice).
   * UI can use this to show "Ti sto sentendo".
   */
  onSpeechStart?: () => void;
  /**
   * Called when auto-stop fires due to silence. Use to swap the UI
   * label to "Trascrizione…" before stop() resolves.
   */
  onAutoStop?: () => void;
}

export interface MicPipelineDiagnostics {
  /** Highest dBFS observed during the session (typical voice -25..-15). */
  maxDb: number;
  /** Floor dBFS (typical -60..-50 in silence, -45..-35 with TV). */
  noiseFloorDb: number;
  /** Cumulative ms of detected voice. */
  voiceMs: number;
  /** Trailing silence ms at stop time. */
  silenceTailMs: number;
  /** Total recording duration ms. */
  recordedMs: number;
  /** Raw blob size in bytes. */
  blobBytes: number;
  /** Why we stopped: 'manual' | 'auto-vad' | 'max-duration' | 'error'. */
  stopReason: 'manual' | 'auto-vad' | 'max-duration' | 'error';
}

export interface MicSession {
  /** Stop recording and return the blob + diagnostics. Idempotent. */
  stop: () => Promise<{ blob: Blob; mime: string; diag: MicPipelineDiagnostics }>;
  /** Abort without producing a blob — used on UI cancel / unmount. */
  abort: () => void;
  /** Read-only snapshot of current diagnostics (for UI overlays). */
  getDiag: () => MicPipelineDiagnostics;
}

/** dBFS from an RMS amplitude in [0, 1]. Returns -Infinity on 0. */
function rmsToDb(rms: number): number {
  if (rms <= 0) return -120;
  return 20 * Math.log10(rms);
}

function normaliseDb(db: number): number {
  // -60 dB → 0, -10 dB → 1. Anything quieter pegs at 0; louder at 1.
  const lo = -60;
  const hi = -10;
  if (db <= lo) return 0;
  if (db >= hi) return 1;
  return (db - lo) / (hi - lo);
}

export function micPipelineAvailable(): boolean {
  if (typeof window === 'undefined') return false;
  if (!('MediaRecorder' in window)) return false;
  if (!navigator.mediaDevices?.getUserMedia) return false;
  if (typeof window.AudioContext === 'undefined' &&
      typeof (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext === 'undefined') return false;
  return true;
}

/** Pick the best supported MIME type for MediaRecorder. */
function pickMimeType(): string {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', ''];
  for (const m of candidates) {
    if (m === '') return '';
    if (window.MediaRecorder?.isTypeSupported?.(m)) return m;
  }
  return '';
}

export async function startMicSession(opts: MicPipelineOptions = {}): Promise<MicSession> {
  if (!micPipelineAvailable()) {
    throw new Error('Microfono non supportato in questo browser');
  }

  const maxDurationMs = opts.maxDurationMs ?? 30_000;
  const vadMode = opts.vadMode ?? 'auto';
  const minVoiceMs = opts.minVoiceMs ?? 600;
  const silenceTailMs = opts.silenceTailMs ?? 1200;

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      sampleRate: 48000,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });

  const mimeType = pickMimeType();
  const recorder = new MediaRecorder(
    stream,
    mimeType ? { mimeType, audioBitsPerSecond: 64_000 } : undefined,
  );
  const chunks: BlobPart[] = [];
  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };

  // Web Audio meter — parallel to MediaRecorder, same stream.
  const AudioCtx = window.AudioContext
    || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const audioCtx = new AudioCtx();
  const source = audioCtx.createMediaStreamSource(stream);
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 1024;
  analyser.smoothingTimeConstant = 0.6;   // 0=raw, 1=very smooth
  source.connect(analyser);
  const buf = new Float32Array(analyser.fftSize);

  // Diagnostics accumulated across the session.
  let maxDb = -120;
  let noiseFloorDb = -60;
  let voiceMs = 0;
  let lastVoiceAt = 0;
  let speechSeen = false;
  let stopReason: MicPipelineDiagnostics['stopReason'] = 'manual';
  const startedAt = performance.now();

  // First 300 ms = noise-floor calibration window.
  const calibrateUntil = startedAt + 300;
  const calibrationSamples: number[] = [];

  // Stable speech threshold: max(-45 dB, floor + 6 dB). Computed once
  // calibration completes. Until then we use a conservative -42 dB so
  // we never miss a loud "ciao".
  let speechThresholdDb = -42;

  let rafHandle: number | null = null;
  let lastFrameAt = startedAt;

  function tick() {
    rafHandle = requestAnimationFrame(tick);
    const now = performance.now();
    analyser.getFloatTimeDomainData(buf);
    // RMS over the buffer.
    let sumSq = 0;
    for (let i = 0; i < buf.length; i++) sumSq += buf[i] * buf[i];
    const rms = Math.sqrt(sumSq / buf.length);
    const db = rmsToDb(rms);
    if (db > maxDb) maxDb = db;

    // Calibration
    if (now < calibrateUntil) {
      calibrationSamples.push(db);
    } else if (calibrationSamples.length > 0) {
      // Use the 80th-percentile of the calibration window as the
      // noise floor — robust against an early click/touch artifact.
      const sorted = [...calibrationSamples].sort((a, b) => a - b);
      noiseFloorDb = sorted[Math.floor(sorted.length * 0.8)] ?? -60;
      speechThresholdDb = Math.max(-45, noiseFloorDb + 6);
      calibrationSamples.length = 0;
    }

    // Voice detection
    const isVoice = now >= calibrateUntil && db > speechThresholdDb;
    const deltaMs = now - lastFrameAt;
    lastFrameAt = now;
    if (isVoice) {
      voiceMs += deltaMs;
      lastVoiceAt = now;
      if (!speechSeen) {
        speechSeen = true;
        opts.onSpeechStart?.();
      }
    }

    // Live meter
    opts.onLevel?.(db, normaliseDb(db));

    // Auto-VAD stop
    if (vadMode === 'auto' && speechSeen && voiceMs >= minVoiceMs) {
      const silenceMs = now - lastVoiceAt;
      if (silenceMs >= silenceTailMs) {
        stopReason = 'auto-vad';
        opts.onAutoStop?.();
        // Trigger stop via the public path so the diag-snapshot is
        // taken from the same code path as a manual stop.
        void session.stop();
        return;
      }
    }

    // Hard cap
    if (now - startedAt >= maxDurationMs) {
      stopReason = 'max-duration';
      void session.stop();
    }
  }
  rafHandle = requestAnimationFrame(tick);

  recorder.start(500);

  let stopped = false;
  let stopResolver: ((v: { blob: Blob; mime: string; diag: MicPipelineDiagnostics }) => void) | null = null;
  let stopPromise: Promise<{ blob: Blob; mime: string; diag: MicPipelineDiagnostics }> | null = null;

  function cleanup() {
    if (rafHandle !== null) {
      cancelAnimationFrame(rafHandle);
      rafHandle = null;
    }
    try { audioCtx.close(); } catch { /* noop */ }
    for (const t of stream.getTracks()) t.stop();
  }

  function buildDiag(): MicPipelineDiagnostics {
    const recordedMs = performance.now() - startedAt;
    return {
      maxDb: round(maxDb),
      noiseFloorDb: round(noiseFloorDb),
      voiceMs: Math.round(voiceMs),
      silenceTailMs: Math.round(performance.now() - lastVoiceAt),
      recordedMs: Math.round(recordedMs),
      blobBytes: 0,                                  // filled in onstop
      stopReason,
    };
  }

  const session: MicSession = {
    stop: async () => {
      if (stopped && stopPromise) return stopPromise;
      stopped = true;
      stopPromise = new Promise((resolve) => { stopResolver = resolve; });
      recorder.onstop = () => {
        const blob = new Blob(chunks, { type: mimeType || 'audio/webm' });
        const diag = buildDiag();
        diag.blobBytes = blob.size;
        cleanup();
        stopResolver?.({ blob, mime: mimeType || 'audio/webm', diag });
      };
      try {
        if (recorder.state === 'recording') recorder.stop();
        else stopResolver?.({ blob: new Blob([], { type: 'audio/webm' }), mime: 'audio/webm', diag: buildDiag() });
      } catch {
        stopReason = 'error';
        cleanup();
        stopResolver?.({ blob: new Blob([], { type: 'audio/webm' }), mime: 'audio/webm', diag: buildDiag() });
      }
      return stopPromise;
    },
    abort: () => {
      if (stopped) return;
      stopped = true;
      try { recorder.stop(); } catch { /* noop */ }
      cleanup();
    },
    getDiag: buildDiag,
  };
  return session;
}

function round(n: number): number {
  return Math.round(n * 10) / 10;
}


// ── Diagnostic message helper ────────────────────────────────────


/**
 * Map a session's diagnostics to a human Italian message explaining
 * WHY an ASR session produced an empty / low-confidence transcript.
 * This is what the user actually needs to know — "non ho capito"
 * is not actionable, "controlla il microfono" is.
 */
export function diagnoseMicFailure(
  diag: MicPipelineDiagnostics,
  asrText: string,
  confidence?: string,
): string | null {
  if (asrText && (confidence === 'high' || confidence === 'medium')) return null;
  if (diag.maxDb < -50) {
    return 'Non sento il microfono. Controlla che non sia mutato o coperto.';
  }
  if (diag.voiceMs < 400) {
    return 'Registrazione troppo breve. Parla un attimo più a lungo.';
  }
  if (diag.maxDb < -38) {
    return 'Sento qualcosa ma molto piano. Parla un po\' più forte o vicino.';
  }
  if (asrText && confidence === 'low') {
    return `Ho capito "${asrText}" — non sono sicura. Ripeti, per favore.`;
  }
  return 'Audio ricevuto ma non sono riuscita a riconoscerlo. Ripeti più lentamente.';
}
