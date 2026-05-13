/**
 * Face recognition provider — orchestrates the worker + per-frame loop.
 *
 * Phase 1: detection only. The provider mounts the worker lazily (first
 * time a consumer asks for detection), throttles frame capture, and
 * exposes the latest `FaceDetection[]` to consumers via `useFaceContext`.
 *
 * Mounting strategy: the provider sits near the app root but does NOT
 * start the worker on mount — only when `start(video)` is called by a
 * surface that has a real <video> stream (Wall, settings preview, etc.).
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

import type { FaceDetection, FaceWorkerIn, FaceWorkerOut } from './types';

const MODELS_BASE_URL = '/models/face-api';
const DOWNSCALE_WIDTH = 480;
const DOWNSCALE_HEIGHT = 360;
const DETECTOR_INPUT_SIZE = 320; // tinyFaceDetector — 224|320|416|512|608
const TARGET_FPS = 5;

interface FaceApi {
  /** Latest detections from the worker. */
  detections: FaceDetection[];
  /** Last frame processing time, ms. Useful for adaptive throttling. */
  lastDurationMs: number;
  /** True once tinyFaceDetector finished loading. */
  modelsReady: boolean;
  /** Last init / detect error message. */
  lastError: string | null;
  /** Start the detection loop on the given video element. */
  start: (video: HTMLVideoElement) => void;
  /** Stop the loop, free the worker, drop detections. */
  stop: () => void;
}

const FaceCtx = createContext<FaceApi | null>(null);

export function FaceProvider({ children }: { children: ReactNode }) {
  const workerRef = useRef<Worker | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const frameTimerRef = useRef<number | null>(null);
  const frameCounterRef = useRef(0);
  const offscreenRef = useRef<OffscreenCanvas | null>(null);
  const inflightRef = useRef(false);

  const [detections, setDetections] = useState<FaceDetection[]>([]);
  const [lastDurationMs, setLastDurationMs] = useState(0);
  const [modelsReady, setModelsReady] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);

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
      } else if (msg.type === 'detections') {
        setDetections(msg.detections);
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
  }, []);

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
      };
      worker.postMessage(msg, [bitmap]);
    } catch (err) {
      inflightRef.current = false;
      setLastError(err instanceof Error ? err.message : String(err));
    }
  }, []);

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
    videoRef.current = null;
    setDetections([]);
    if (workerRef.current) {
      const msg: FaceWorkerIn = { type: 'shutdown' };
      workerRef.current.postMessage(msg);
      workerRef.current.terminate();
      workerRef.current = null;
      setModelsReady(false);
    }
  }, []);

  useEffect(() => {
    return () => {
      if (frameTimerRef.current != null) window.clearInterval(frameTimerRef.current);
      if (workerRef.current) workerRef.current.terminate();
    };
  }, []);

  const api = useMemo<FaceApi>(
    () => ({ detections, lastDurationMs, modelsReady, lastError, start, stop }),
    [detections, lastDurationMs, modelsReady, lastError, start, stop],
  );

  return <FaceCtx.Provider value={api}>{children}</FaceCtx.Provider>;
}

export function useFaceContext(): FaceApi {
  const ctx = useContext(FaceCtx);
  if (!ctx) throw new Error('useFaceContext must be used inside <FaceProvider>');
  return ctx;
}
