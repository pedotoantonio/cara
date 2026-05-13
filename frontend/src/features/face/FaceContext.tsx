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

import { listDescriptors, listFaceProfiles } from '../../api/face';

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
const TARGET_FPS = 5;

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

  // Smoothing state, kept in refs so it doesn't re-render on every update.
  const trackersRef = useRef<Map<string, ConfirmationTracker>>(new Map());
  const lastSeenAtRef = useRef<Map<string, number>>(new Map());
  const lostTimerRef = useRef<number | null>(null);

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

  const onDetections = useCallback(
    (incoming: FaceDetection[]) => {
      const now = performance.now();

      // Sort by area descending, then cap to the multi-face limit. The
      // biggest box is the closest face: that's who CARA addresses.
      const ordered = [...incoming]
        .sort((a, b) => computeArea(b) - computeArea(a))
        .slice(0, MAX_TRACKED_FACES);

      if (ordered.length === 0) {
        scheduleLostCheck();
      }

      for (const d of ordered) {
        emit({ kind: 'face.detected', trackId: d.trackId, score: d.score });

        if (d.identity) {
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

      scheduleLostCheck();
    },
    [emit, scheduleLostCheck],
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

  const start = useCallback(
    (video: HTMLVideoElement) => {
      videoRef.current = video;
      ensureWorker();
      if (frameTimerRef.current != null) return;
      frameTimerRef.current = window.setInterval(captureAndPost, 1000 / TARGET_FPS);
    },
    [ensureWorker, captureAndPost],
  );

  const stop = useCallback(() => {
    if (frameTimerRef.current != null) {
      window.clearInterval(frameTimerRef.current);
      frameTimerRef.current = null;
    }
    if (lostTimerRef.current != null) {
      window.clearTimeout(lostTimerRef.current);
      lostTimerRef.current = null;
    }
    videoRef.current = null;
    trackersRef.current.clear();
    lastSeenAtRef.current.clear();
    setDetections([]);
    setPrimarySubject(null);
    setCompanions([]);
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
      if (frameTimerRef.current != null) window.clearInterval(frameTimerRef.current);
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
