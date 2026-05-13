/**
 * Face recognition feature — shared types.
 *
 * Phase 1: detection only (bounding boxes + score). No descriptors, no
 * identity match yet. Types for descriptors / profiles are declared now
 * to keep the contract stable across phases.
 */

export interface FaceBox {
  /** Top-left x in source image coords (post-downscale). */
  x: number;
  y: number;
  width: number;
  height: number;
}

/** One face as returned by the worker after a single frame. */
export interface FaceDetection {
  /** Stable per-frame index; useful for temporal smoothing later. */
  trackId: number;
  box: FaceBox;
  /** Detector confidence 0..1. */
  score: number;
  /** Optional 128-D descriptor (filled from Phase 2 onward). */
  descriptor?: Float32Array;
  /** Best identity match (filled from Phase 2 onward). */
  identity?: {
    profileId: string;
    displayName: string;
    distance: number;
  };
}

/** Worker → main message. */
export type FaceWorkerOut =
  | { type: 'ready'; modelsLoaded: string[] }
  | { type: 'detections'; frameId: number; detections: FaceDetection[]; durationMs: number }
  | { type: 'error'; message: string };

/** Main → worker message. */
export type FaceWorkerIn =
  | { type: 'init'; modelsBaseUrl: string }
  | { type: 'detect'; frameId: number; bitmap: ImageBitmap; inputSize: number }
  | { type: 'shutdown' };

/** Persisted face profile (backend-side shape). */
export interface FaceProfile {
  id: string;
  displayName: string;
  isChild: boolean;
  matchThreshold: number;
  active: boolean;
  consentGivenAt: string | null;
  consentTextVersion: string | null;
  descriptorCount: number;
  lastRecognizedAt: string | null;
  recognitionCount: number;
  createdAt: string;
}

export interface FaceSettings {
  enabled: boolean;
  defaultThreshold: number;
  expressionEnabled: boolean;
  ageGenderEnabled: boolean;
}
