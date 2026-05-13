/**
 * Face recognition feature — shared types.
 *
 * Phase 2: detection + 128-D descriptor + local identity match against
 * a profile cache uploaded once from the backend.
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
  /** Stable per-frame index; combined with temporal smoothing for tracking. */
  trackId: number;
  box: FaceBox;
  /** Detector confidence 0..1. */
  score: number;
  /** 128-D descriptor (only when recognition nets have been loaded). */
  descriptor?: Float32Array;
  /** Best identity match (only when a profile is below its threshold). */
  identity?: {
    profileId: string;
    displayName: string;
    isChild: boolean;
    distance: number;
  };
}

/** Profile cache row uploaded once to the worker for local matching. */
export interface WorkerProfile {
  profileId: string;
  displayName: string;
  isChild: boolean;
  matchThreshold: number;
  /** All known descriptors for this profile, packed for fast distance loops. */
  descriptors: Float32Array[];
}

/** Worker → main message. */
export type FaceWorkerOut =
  | { type: 'ready'; modelsLoaded: string[] }
  | { type: 'recognitionReady' }
  | { type: 'profilesLoaded'; count: number }
  | {
      type: 'detections';
      frameId: number;
      detections: FaceDetection[];
      durationMs: number;
    }
  | { type: 'error'; message: string };

/** Main → worker message. */
export type FaceWorkerIn =
  | { type: 'init'; modelsBaseUrl: string }
  | { type: 'loadRecognition' }
  | { type: 'setProfiles'; profiles: WorkerProfile[] }
  | {
      type: 'detect';
      frameId: number;
      bitmap: ImageBitmap;
      inputSize: number;
      withDescriptor: boolean;
    }
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

/** Stored descriptor as returned by `GET /face/profiles/{id}/descriptors`. */
export interface StoredDescriptor {
  id: string;
  profileId: string;
  descriptor: number[];
  source: 'enrollment' | 'continuous';
  quality: number | null;
  createdAt: string;
}

export interface FaceSettings {
  enabled: boolean;
  defaultThreshold: number;
  expressionEnabled: boolean;
  ageGenderEnabled: boolean;
}

/** Identity payload as carried by detection results and events. */
export interface FaceIdentity {
  profileId: string;
  displayName: string;
  isChild: boolean;
  distance: number;
}

/** Lifecycle events emitted on the FaceContext local bus. */
export type FaceEvent =
  | { kind: 'face.detected'; trackId: number; score: number }
  | {
      kind: 'face.identified';
      profileId: string;
      displayName: string;
      isChild: boolean;
      distance: number;
      /** Other identified faces also in the scene at the moment. */
      companions: FaceIdentity[];
    }
  | { kind: 'face.unknown_present'; trackId: number }
  | { kind: 'face.lost'; profileId: string | null };

export type FaceEventHandler = (event: FaceEvent) => void;
