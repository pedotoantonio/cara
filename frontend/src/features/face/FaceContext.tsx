/**
 * Face recognition provider — orchestrates the worker, profile cache,
 * per-frame loop, temporal smoothing, and a local event bus.
 *
 * Surfaces consume the context for two things:
 *   1. Live detection state via `useFaceContext()` (e.g. the FaceOverlay).
 *   2. Lifecycle events via `onEvent(...)` (e.g. CARA Core firing a
 *      "Ciao Sara" line on `face.identified`).
 *
 * The worker is spawned lazily on the first `start(video)` call to keep
 * the cold start cheap for users who never use the feature. The profile
 * cache is fetched once per provider lifetime — call `refreshProfiles()`
 * after an enrollment to pick up new descriptors.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { addDescriptors, listDescriptors, listFaceProfiles } from '../../api/face';

import type {
  FaceDetection,
  FaceEvent,
  FaceEventHandler,
  FaceIdentity,
  FaceWorkerIn,
  FaceWorkerOut,
  WorkerProfile,
} from './types';

const MODELS_BASE_URL = '/models/face-api';
const DOWNSCALE_WIDTH = 480;
const DOWNSCALE_HEIGHT = 360;
const DETECTOR_INPUT_SIZE = 320;

// Temporal smoothing: a person must be seen in this many consecutive
// frames within `IDENTIFY_WINDOW_MS` before we fire `face.identified`.
// And once we've identified someone, we hold the state for
// `LOST_TIMEOUT_MS` after the last sighting before firing `face.lost`.
const IDENTIFY_MIN_FRAMES = 3;
const IDENTIFY_WINDOW_MS = 1000;
const LOST_TIMEOUT_MS = 2000;

// Multi-face cap. Beyond this we drop the smallest boxes so the worker
// stays responsive and the avatar doesn't try to address a crowd. 4 is
// enough for the household configurations we care about.
const MAX_TRACKED_FACES = 4;

// ── Adaptive frame loop ──────────────────────────────────────────────
// We don't run on a fixed setInterval — instead we re-schedule each
// frame based on the moving average of the last N worker durations.
// On a slow device (Pi-class, heavy frigate load) we settle around
// 3-4 FPS; on an M1 the loop tops out at MIN_INTERVAL_MS = 50 ms (20 FPS).
const MIN_INTERVAL_MS = 50;           // hard ceiling at ~20 FPS
const MAX_INTERVAL_MS = 1000;         // hard floor at 1 FPS
const DEFAULT_INTERVAL_MS = 200;      // 5 FPS — the spec's "watch" mode
const SLOW_THRESHOLD_MS = 200;        // average > this → slow down
const FAST_THRESHOLD_MS = 80;         // average < this → speed up
const DURATION_BUFFER_SIZE = 10;      // rolling window for the average

// ── Idle mode ────────────────────────────────────────────────────────
// After IDLE_AFTER_MS with no detected face we throttle to IDLE_INTERVAL_MS
// (1 FPS). The first detection above the idle threshold snaps us back
// to the adaptive rate so the user doesn't notice a lag on return.
const IDLE_AFTER_MS = 30_000;
const IDLE_INTERVAL_MS = 1000;        // 1 FPS while no one is around

// ── Anti-spoofing (sec. 14) ──────────────────────────────────────────
// A photo of a face has zero micro-movement. Real heads jitter at least
// a few pixels per second from blinking + posture shift. We track the
// centroid of the primary detection over a ~1 s window and require its
// max - min to exceed STATIC_PIXEL_THRESHOLD on at least one axis. Below
// that we suspect a printed photo and refuse to confirm an identity.
const STATIC_SAMPLE_WINDOW_MS = 1000;
const STATIC_PIXEL_THRESHOLD = 3;     // in source-frame px (480x360)

// ── Continuous learning (sec. 11.3) ──────────────────────────────────
// Every CONTINUOUS_CAPTURE_EVERY consecutive confirmed frames for the
// same primary profile, we POST the latest descriptor as
// source='continuous'. This widens the descriptor cluster over months
// (haircut, beard, lighting). Throttled per-run so we don't hammer the
// backend on a long conversation.
const CONTINUOUS_CAPTURE_EVERY = 50;
const CONTINUOUS_MIN_QUALITY = 0.7;

interface ConfirmationTracker {
  /** Most recent N timestamps for the same identity. */
  timestamps: number[];
  /** True once we've fired `face.identified` for this run. */
  confirmed: boolean;
}

interface FaceApi {
  /** Latest detections from the worker (smoothed `identity` field).
   *  Capped at MAX_TRACKED_FACES, sorted by area descending. */
  detections: FaceDetection[];
  /** The biggest (= closest) identified face. The avatar should address
   *  this one by name. Null until smoothing confirms an identity. */
  primarySubject: FaceIdentity | null;
  /** Other identified faces in the scene, ordered by area descending. */
  companions: FaceIdentity[];
  /** Backwards-compat alias for primarySubject — same value. */
  confirmedIdentity: FaceIdentity | null;
  /** Last frame processing time, ms. */
  lastDurationMs: number;
  /** Current capture interval (ms). Surfaces use this to show the
   *  effective FPS in a diagnostics panel. */
  currentIntervalMs: number;
  /** True while we're in 1-FPS power-save mode (no faces for >30 s). */
  idle: boolean;
  /** True when the primary face has been static for > 1 s — likely a
   *  printed photo. We suppress identity confirmation in this state. */
  spoofingSuspected: boolean;
  /** True once tinyFaceDetector finished loading. */
  modelsReady: boolean;
  /** True once landmark + recognition nets are loaded. */
  recognitionReady: boolean;
  /** Number of profiles uploaded to the worker. */
  profilesCount: number;
  /** Last init / detect error message. */
  lastError: string | null;

  /** Start the detection loop on the given video element. */
  start: (video: HTMLVideoElement) => void;
  /** Stop the loop, free the worker, drop detections. */
  stop: () => void;
  /** Fetch profiles + descriptors and push them into the worker cache. */
  refreshProfiles: () => Promise<void>;
  /** Ask the worker to load landmark + recognition nets (~6.8 MB). */
  enableRecognition: () => void;

  /** Subscribe to face lifecycle events. Returns an unsubscribe fn. */
  onEvent: (handler: FaceEventHandler) => () => void;
}

const FaceCtx = createContext<FaceApi | null>(null);

export function FaceProvider({ children }: { children: ReactNode }) {
  const workerRef = useRef<Worker | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const frameTimerRef = useRef<number | null>(null);
  const frameCounterRef = useRef(0);
  const offscreenRef = useRef<OffscreenCanvas | null>(null);
  const inflightRef = useRef(false);
  const recognitionRequestedRef = useRef(false);

  const [detections, setDetections] = useState<FaceDetection[]>([]);
  const [lastDurationMs, setLastDurationMs] = useState(0);
  const [modelsReady, setModelsReady] = useState(false);
  const [recognitionReady, setRecognitionReady] = useState(false);
  const [profilesCount, setProfilesCount] = useState(0);
  const [lastError, setLastError] = useState<string | null>(null);
  const [primarySubject, setPrimarySubject] = useState<FaceIdentity | null>(null);
  const [companions, setCompanions] = useState<FaceIdentity[]>([]);
  const [currentIntervalMs, setCurrentIntervalMs] = useState(DEFAULT_INTERVAL_MS);
  const [idle, setIdle] = useState(false);
  const [spoofingSuspected, setSpoofingSuspected] = useState(false);

  // Smoothing state, kept in refs so it doesn't re-render on every update.
  const trackersRef = useRef<Map<string, ConfirmationTracker>>(new Map());
  const lastSeenAtRef = useRef<Map<string, number>>(new Map());
  const lostTimerRef = useRef<number | null>(null);

  // Performance + idle state — also refs so they don't trigger re-renders.
  const durationBufferRef = useRef<number[]>([]);
  const adaptiveIntervalRef = useRef(DEFAULT_INTERVAL_MS);
  const idleRef = useRef(false);
  const lastFaceSeenAtRef = useRef<number>(performance.now());

  // Anti-spoofing: rolling centroid samples for the primary detection.
  const centroidSamplesRef = useRef<{ t: number; cx: number; cy: number }[]>([]);
  const spoofingRef = useRef(false);

  // Continuous learning: per-profile consecutive-confirmed-frame counter.
  // We POST a new descriptor every CONTINUOUS_CAPTURE_EVERY hits.
  const continuousCounterRef = useRef<Map<string, number>>(new Map());
  const continuousInflightRef = useRef<Set<string>>(new Set());

  // Local event bus — Set so handlers can be added/removed cheaply.
  const handlersRef = useRef<Set<FaceEventHandler>>(new Set());

  const emit = useCallback((event: FaceEvent) => {
    for (const h of handlersRef.current) {
      try {
        h(event);
      } catch (err) {
        // A bad subscriber must not poison the bus.
        // eslint-disable-next-line no-console
        console.error('face event handler threw', err);
      }
    }
  }, []);

  const scheduleLostCheck = useCallback(() => {
    if (lostTimerRef.current != null) return;
    lostTimerRef.current = window.setTimeout(() => {
      lostTimerRef.current = null;
      const now = performance.now();
      let stillThere = false;
      for (const [pid, lastSeen] of lastSeenAtRef.current.entries()) {
        if (now - lastSeen <= LOST_TIMEOUT_MS) {
          stillThere = true;
          continue;
        }
        // Lost: forget the tracker and emit.
        lastSeenAtRef.current.delete(pid);
        trackersRef.current.delete(pid);
        emit({ kind: 'face.lost', profileId: pid });
      }
      if (!stillThere) {
        setPrimarySubject(null);
        setCompanions([]);
      } else {
        scheduleLostCheck();
      }
    }, LOST_TIMEOUT_MS);
  }, [emit]);

  const computeArea = (d: FaceDetection) => d.box.width * d.box.height;

  /**
   * Push the primary face centroid into the rolling sample buffer and
   * decide whether the head is moving enough to count as a real person
   * (vs. a photo held up to the camera).
   */
  const updateSpoofingSignal = useCallback(
    (primary: FaceDetection | null, now: number): boolean => {
      const samples = centroidSamplesRef.current;
      // Drop samples older than the rolling window.
      while (samples.length > 0 && now - samples[0].t > STATIC_SAMPLE_WINDOW_MS) {
        samples.shift();
      }
      if (primary == null) {
        // Without a primary we can't decide either way. Don't keep the
        // last "static" verdict stuck — clear it. We won't confirm a new
        // identity until we have fresh samples anyway.
        if (spoofingRef.current) {
          spoofingRef.current = false;
          setSpoofingSuspected(false);
        }
        return false;
      }
      const cx = primary.box.x + primary.box.width / 2;
      const cy = primary.box.y + primary.box.height / 2;
      samples.push({ t: now, cx, cy });

      // We need at least a few samples spread across the window before
      // calling a face "static" — a fresh detection is always static.
      if (samples.length < 4 || now - samples[0].t < STATIC_SAMPLE_WINDOW_MS * 0.7) {
        return spoofingRef.current;
      }
      let minX = Infinity,
        maxX = -Infinity,
        minY = Infinity,
        maxY = -Infinity;
      for (const s of samples) {
        if (s.cx < minX) minX = s.cx;
        if (s.cx > maxX) maxX = s.cx;
        if (s.cy < minY) minY = s.cy;
        if (s.cy > maxY) maxY = s.cy;
      }
      const isStatic =
        maxX - minX < STATIC_PIXEL_THRESHOLD &&
        maxY - minY < STATIC_PIXEL_THRESHOLD;
      if (isStatic !== spoofingRef.current) {
        spoofingRef.current = isStatic;
        setSpoofingSuspected(isStatic);
      }
      return isStatic;
    },
    [],
  );

  /**
   * Continuous learning — every CONTINUOUS_CAPTURE_EVERY frames where the
   * same profile is the *single confirmed primary*, capture the current
   * descriptor as source='continuous'. Throttled per (profileId, run)
   * with inflight tracking so a slow POST can't trigger a second one.
   */
  const maybeCaptureContinuous = useCallback(
    (primary: FaceDetection | null) => {
      if (!primary?.identity || !primary?.descriptor) {
        // Reset all counters when the primary is absent or unknown — we
        // don't want a long unknown stretch to accidentally tip the
        // counter past the threshold once a profile reappears.
        if (continuousCounterRef.current.size > 0) {
          continuousCounterRef.current.clear();
        }
        return;
      }
      const pid = primary.identity.profileId;
      const next = (continuousCounterRef.current.get(pid) ?? 0) + 1;
      continuousCounterRef.current.set(pid, next);

      if (next < CONTINUOUS_CAPTURE_EVERY) return;
      if (continuousInflightRef.current.has(pid)) return;

      // Compute a coarse quality from the detector score + a 1.0 bonus
      // when the box is sufficiently large.
      const areaRatio =
        (primary.box.width * primary.box.height) /
        (DOWNSCALE_WIDTH * DOWNSCALE_HEIGHT);
      const quality = Math.min(
        1,
        primary.score * Math.min(1, areaRatio / 0.2),
      );
      if (quality < CONTINUOUS_MIN_QUALITY) {
        // Quality too low — wait for a better frame, but don't fire.
        // Reset the counter so we re-arm rather than spam on every frame.
        continuousCounterRef.current.set(pid, 0);
        return;
      }

      continuousInflightRef.current.add(pid);
      continuousCounterRef.current.set(pid, 0);
      const descriptor = Array.from(primary.descriptor);
      void addDescriptors(pid, [
        { descriptor, source: 'continuous', quality },
      ])
        .catch((err) => {
          setLastError(err instanceof Error ? err.message : String(err));
        })
        .finally(() => {
          continuousInflightRef.current.delete(pid);
        });
    },
    [],
  );

  const onDetections = useCallback(
    (incoming: FaceDetection[]) => {
      const now = performance.now();

      // Sort by area descending, then cap to the multi-face limit. The
      // biggest box is the closest face: that's who CARA addresses.
      const ordered = [...incoming]
        .sort((a, b) => computeArea(b) - computeArea(a))
        .slice(0, MAX_TRACKED_FACES);

      // Update last-face-seen + flip out of idle on first detection.
      if (ordered.length > 0) {
        lastFaceSeenAtRef.current = now;
        if (idleRef.current) {
          idleRef.current = false;
          setIdle(false);
        }
      } else {
        scheduleLostCheck();
      }

      // Anti-spoofing: only the primary's centroid feeds the variance.
      // Companions can't spoof — we never confirm them as the addressee.
      const isStatic = updateSpoofingSignal(ordered[0] ?? null, now);

      for (let i = 0; i < ordered.length; i++) {
        const d = ordered[i];
        emit({ kind: 'face.detected', trackId: d.trackId, score: d.score });

        if (d.identity) {
          // If the *primary* face is static, treat the identity as
          // unconfirmed — likely a printed photo of a known person.
          if (i === 0 && isStatic) continue;
          const pid = d.identity.profileId;
          lastSeenAtRef.current.set(pid, now);

          let tracker = trackersRef.current.get(pid);
          if (!tracker) {
            tracker = { timestamps: [], confirmed: false };
            trackersRef.current.set(pid, tracker);
          }
          tracker.timestamps = [
            ...tracker.timestamps.filter((t) => now - t <= IDENTIFY_WINDOW_MS),
            now,
          ];
        } else if (d.descriptor) {
          emit({ kind: 'face.unknown_present', trackId: d.trackId });
        }
      }

      // Smoothed detections: drop tentative identities so the overlay
      // doesn't flicker between {unknown, identified, unknown}.
      const smoothed = ordered.map((d) => {
        if (!d.identity) return d;
        const tracker = trackersRef.current.get(d.identity.profileId);
        return tracker?.confirmed ? d : { ...d, identity: undefined };
      });
      setDetections(smoothed);

      // Resolve primary + companions from the *confirmed* identities in
      // the ordered set. Primary is the biggest confirmed; companions are
      // the rest of the confirmed identities, area-descending.
      const confirmed: FaceIdentity[] = [];
      for (const d of ordered) {
        if (!d.identity) continue;
        const tracker = trackersRef.current.get(d.identity.profileId);
        if (tracker?.confirmed) confirmed.push(d.identity);
      }
      const newPrimary = confirmed[0] ?? null;
      const newCompanions = confirmed.slice(1);

      // Detect *new* confirmations and a primary swap so we can fire
      // face.identified exactly once per (profile, run).
      for (const d of ordered) {
        if (!d.identity) continue;
        const tracker = trackersRef.current.get(d.identity.profileId);
        if (!tracker || tracker.confirmed) continue;
        if (tracker.timestamps.length >= IDENTIFY_MIN_FRAMES) {
          tracker.confirmed = true;
          // Build the companion list for the event payload at firing time
          // — same logic as primary but excluding the firing profile.
          const others = confirmed
            .filter((c) => c.profileId !== d.identity!.profileId);
          emit({
            kind: 'face.identified',
            profileId: d.identity.profileId,
            displayName: d.identity.displayName,
            isChild: d.identity.isChild,
            distance: d.identity.distance,
            companions: others,
          });
        }
      }

      setPrimarySubject((prev) => {
        // Avoid pointless re-renders if the identity stayed the same.
        if (prev?.profileId === newPrimary?.profileId) return prev;
        return newPrimary;
      });
      setCompanions((prev) => {
        const sameLength = prev.length === newCompanions.length;
        const sameOrder =
          sameLength && prev.every((p, i) => p.profileId === newCompanions[i].profileId);
        return sameOrder ? prev : newCompanions;
      });

      // Continuous learning — only when the primary is confirmed, not
      // static, and is actually the one we treat as confirmed primary.
      const primaryDetection = ordered[0] ?? null;
      const primaryConfirmed =
        primaryDetection?.identity &&
        trackersRef.current.get(primaryDetection.identity.profileId)?.confirmed;
      if (primaryConfirmed && !isStatic) {
        maybeCaptureContinuous(primaryDetection);
      } else {
        maybeCaptureContinuous(null);
      }

      scheduleLostCheck();
    },
    [emit, scheduleLostCheck, updateSpoofingSignal, maybeCaptureContinuous],
  );

  const ensureWorker = useCallback(() => {
    if (workerRef.current) return workerRef.current;

    const w = new Worker(
      new URL('./face.worker.ts', import.meta.url),
      { type: 'module', name: 'face-recognition' },
    );

    w.addEventListener('message', (ev: MessageEvent<FaceWorkerOut>) => {
      const msg = ev.data;
      if (msg.type === 'ready') {
        setModelsReady(true);
        setLastError(null);
        if (recognitionRequestedRef.current) {
          const m: FaceWorkerIn = { type: 'loadRecognition' };
          w.postMessage(m);
        }
      } else if (msg.type === 'recognitionReady') {
        setRecognitionReady(true);
      } else if (msg.type === 'profilesLoaded') {
        setProfilesCount(msg.count);
      } else if (msg.type === 'detections') {
        onDetections(msg.detections);
        setLastDurationMs(msg.durationMs);
        // Feed the adaptive throttle: keep the last DURATION_BUFFER_SIZE
        // samples, average, and nudge the interval up or down once we
        // have a full window. The next scheduleNextFrame() will pick up
        // the new value.
        const buf = durationBufferRef.current;
        buf.push(msg.durationMs);
        if (buf.length > DURATION_BUFFER_SIZE) buf.shift();
        if (buf.length === DURATION_BUFFER_SIZE) {
          const avg = buf.reduce((a, b) => a + b, 0) / buf.length;
          let next = adaptiveIntervalRef.current;
          if (avg > SLOW_THRESHOLD_MS) {
            next = Math.min(MAX_INTERVAL_MS, next * 1.3);
          } else if (avg < FAST_THRESHOLD_MS) {
            next = Math.max(MIN_INTERVAL_MS, next * 0.85);
          }
          if (Math.abs(next - adaptiveIntervalRef.current) > 1) {
            adaptiveIntervalRef.current = next;
            if (!idleRef.current) {
              setCurrentIntervalMs(Math.round(next));
            }
          }
        }
        inflightRef.current = false;
      } else if (msg.type === 'error') {
        setLastError(msg.message);
        inflightRef.current = false;
      }
    });

    const init: FaceWorkerIn = { type: 'init', modelsBaseUrl: MODELS_BASE_URL };
    w.postMessage(init);

    workerRef.current = w;
    return w;
  }, [onDetections]);

  const enableRecognition = useCallback(() => {
    recognitionRequestedRef.current = true;
    const worker = ensureWorker();
    if (modelsReady) {
      const m: FaceWorkerIn = { type: 'loadRecognition' };
      worker.postMessage(m);
    }
  }, [ensureWorker, modelsReady]);

  const refreshProfiles = useCallback(async () => {
    try {
      const profiles = await listFaceProfiles();
      const active = profiles.filter((p) => p.active);
      const out: WorkerProfile[] = [];

      for (const p of active) {
        if (p.descriptorCount === 0) continue;
        const rows = await listDescriptors(p.id);
        if (rows.length === 0) continue;
        out.push({
          profileId: p.id,
          displayName: p.displayName,
          isChild: p.isChild,
          matchThreshold: p.matchThreshold,
          descriptors: rows.map((r) => Float32Array.from(r.descriptor)),
        });
      }

      const worker = ensureWorker();
      const transfer = out.flatMap((p) => p.descriptors.map((d) => d.buffer));
      const m: FaceWorkerIn = { type: 'setProfiles', profiles: out };
      worker.postMessage(m, transfer);
    } catch (err) {
      setLastError(err instanceof Error ? err.message : String(err));
    }
  }, [ensureWorker]);

  const captureAndPost = useCallback(async () => {
    const video = videoRef.current;
    const worker = workerRef.current;
    if (!video || !worker || inflightRef.current) return;
    if (video.readyState < 2 || video.videoWidth === 0) return;

    inflightRef.current = true;
    try {
      if (!offscreenRef.current) {
        offscreenRef.current = new OffscreenCanvas(DOWNSCALE_WIDTH, DOWNSCALE_HEIGHT);
      }
      const oc = offscreenRef.current;
      const ctx = oc.getContext('2d');
      if (!ctx) {
        inflightRef.current = false;
        return;
      }
      ctx.drawImage(video, 0, 0, oc.width, oc.height);
      const bitmap = oc.transferToImageBitmap();

      const msg: FaceWorkerIn = {
        type: 'detect',
        frameId: frameCounterRef.current++,
        bitmap,
        inputSize: DETECTOR_INPUT_SIZE,
        withDescriptor: recognitionReady,
      };
      worker.postMessage(msg, [bitmap]);
    } catch (err) {
      inflightRef.current = false;
      setLastError(err instanceof Error ? err.message : String(err));
    }
  }, [recognitionReady]);

  /**
   * Tick = grab a frame, post it, schedule the next tick. The interval
   * comes from `adaptiveIntervalRef` (auto-tuned) clamped to
   * `IDLE_INTERVAL_MS` while idle. Recursive setTimeout instead of a
   * fixed setInterval so changes take effect on the very next tick.
   */
  const scheduleNextFrame = useCallback(() => {
    if (videoRef.current == null) return;
    const now = performance.now();
    if (
      !idleRef.current &&
      now - lastFaceSeenAtRef.current > IDLE_AFTER_MS
    ) {
      idleRef.current = true;
      setIdle(true);
      setCurrentIntervalMs(IDLE_INTERVAL_MS);
    }
    const intervalMs = idleRef.current
      ? IDLE_INTERVAL_MS
      : adaptiveIntervalRef.current;
    frameTimerRef.current = window.setTimeout(() => {
      void captureAndPost();
      scheduleNextFrame();
    }, intervalMs);
  }, [captureAndPost]);

  const start = useCallback(
    (video: HTMLVideoElement) => {
      videoRef.current = video;
      ensureWorker();
      if (frameTimerRef.current != null) return;
      // Reset adaptive + idle state when (re-)starting so a previous
      // run's slow timings don't carry over.
      durationBufferRef.current = [];
      adaptiveIntervalRef.current = DEFAULT_INTERVAL_MS;
      idleRef.current = false;
      lastFaceSeenAtRef.current = performance.now();
      setIdle(false);
      setCurrentIntervalMs(DEFAULT_INTERVAL_MS);
      scheduleNextFrame();
    },
    [ensureWorker, scheduleNextFrame],
  );

  const stop = useCallback(() => {
    if (frameTimerRef.current != null) {
      window.clearTimeout(frameTimerRef.current);
      frameTimerRef.current = null;
    }
    if (lostTimerRef.current != null) {
      window.clearTimeout(lostTimerRef.current);
      lostTimerRef.current = null;
    }
    videoRef.current = null;
    trackersRef.current.clear();
    lastSeenAtRef.current.clear();
    centroidSamplesRef.current = [];
    continuousCounterRef.current.clear();
    continuousInflightRef.current.clear();
    spoofingRef.current = false;
    idleRef.current = false;
    durationBufferRef.current = [];
    adaptiveIntervalRef.current = DEFAULT_INTERVAL_MS;
    setDetections([]);
    setPrimarySubject(null);
    setCompanions([]);
    setSpoofingSuspected(false);
    setIdle(false);
    setCurrentIntervalMs(DEFAULT_INTERVAL_MS);
    if (workerRef.current) {
      const msg: FaceWorkerIn = { type: 'shutdown' };
      workerRef.current.postMessage(msg);
      workerRef.current.terminate();
      workerRef.current = null;
      setModelsReady(false);
      setRecognitionReady(false);
      setProfilesCount(0);
      recognitionRequestedRef.current = false;
    }
  }, []);

  const onEvent = useCallback((handler: FaceEventHandler) => {
    handlersRef.current.add(handler);
    return () => {
      handlersRef.current.delete(handler);
    };
  }, []);

  useEffect(() => {
    return () => {
      if (frameTimerRef.current != null) window.clearTimeout(frameTimerRef.current);
      if (lostTimerRef.current != null) window.clearTimeout(lostTimerRef.current);
      if (workerRef.current) workerRef.current.terminate();
    };
  }, []);

  const api = useMemo<FaceApi>(
    () => ({
      detections,
      primarySubject,
      companions,
      confirmedIdentity: primarySubject,
      lastDurationMs,
      currentIntervalMs,
      idle,
      spoofingSuspected,
      modelsReady,
      recognitionReady,
      profilesCount,
      lastError,
      start,
      stop,
      refreshProfiles,
      enableRecognition,
      onEvent,
    }),
    [
      detections,
      primarySubject,
      companions,
      lastDurationMs,
      currentIntervalMs,
      idle,
      spoofingSuspected,
      modelsReady,
      recognitionReady,
      profilesCount,
      lastError,
      start,
      stop,
      refreshProfiles,
      enableRecognition,
      onEvent,
    ],
  );

  return <FaceCtx.Provider value={api}>{children}</FaceCtx.Provider>;
}

export function useFaceContext(): FaceApi {
  const ctx = useContext(FaceCtx);
  if (!ctx) throw new Error('useFaceContext must be used inside <FaceProvider>');
  return ctx;
}
