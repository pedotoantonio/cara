/**
 * Face recognition Web Worker — Phase 2.
 *
 * Pipeline:
 *
 *   ImageBitmap → tinyFaceDetector → (optionally) faceLandmark68 →
 *   faceRecognitionNet → 128-D descriptor → local match against the
 *   profile cache → FaceDetection[] back to the main thread.
 *
 * Models load in two stages:
 *   - `init`              loads only tinyFaceDetector (193 KB)
 *   - `loadRecognition`   adds landmark68 + recognition nets (~6.8 MB)
 *
 * Recognition is opt-in per-surface so a settings page that only wants
 * to draw bounding boxes (no identification) doesn't pay the download.
 */

import * as faceapi from '@vladmandic/face-api';

import type { FaceWorkerIn, FaceWorkerOut, WorkerProfile } from './types';

let detectorReady = false;
let recognitionReady = false;
let modelsBaseUrl = '/models/face-api';
let trackCounter = 0;
let profiles: WorkerProfile[] = [];

const post = (msg: FaceWorkerOut, transfer?: Transferable[]) =>
  (self as unknown as Worker).postMessage(msg, transfer ?? []);

async function loadDetector(baseUrl: string): Promise<void> {
  modelsBaseUrl = baseUrl;
  await faceapi.nets.tinyFaceDetector.loadFromUri(baseUrl);
  detectorReady = true;
  post({ type: 'ready', modelsLoaded: ['tinyFaceDetector'] });
}

async function loadRecognition(): Promise<void> {
  if (recognitionReady) {
    post({ type: 'recognitionReady' });
    return;
  }
  await Promise.all([
    faceapi.nets.faceLandmark68Net.loadFromUri(modelsBaseUrl),
    faceapi.nets.faceRecognitionNet.loadFromUri(modelsBaseUrl),
  ]);
  recognitionReady = true;
  post({ type: 'recognitionReady' });
}

/**
 * Squared euclidean distance between two 128-D vectors. We compare
 * squared distances against squared thresholds to skip a per-vector
 * Math.sqrt; the relative ordering is the same. (face-api uses plain
 * euclidean and a 0.5 threshold; we keep the same scale by sqrt-ing
 * at the end for the public `distance` field.)
 */
function squaredDistance(a: Float32Array, b: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < a.length; i++) {
    const d = a[i] - b[i];
    sum += d * d;
  }
  return sum;
}

interface BestMatch {
  profile: WorkerProfile;
  distance: number;
  second: number;
}

/**
 * For each profile, take the *minimum* distance across its descriptors
 * (a profile's enrollment shots + continuous updates form a small
 * cluster — being close to any one of them is enough). Pick the best
 * profile, and only report it if it actually beats its own threshold.
 *
 * Ambiguity guard: if the second-best profile is within 0.05 of the
 * best, treat it as unknown to avoid confidently mislabeling siblings
 * / family members with similar features.
 */
function bestMatch(descriptor: Float32Array): BestMatch | null {
  let best: { profile: WorkerProfile; sq: number } | null = null;
  let secondSq = Infinity;

  for (const p of profiles) {
    let minSq = Infinity;
    for (const d of p.descriptors) {
      const sq = squaredDistance(descriptor, d);
      if (sq < minSq) minSq = sq;
    }
    if (best === null || minSq < best.sq) {
      if (best !== null) secondSq = best.sq;
      best = { profile: p, sq: minSq };
    } else if (minSq < secondSq) {
      secondSq = minSq;
    }
  }

  if (best === null) return null;
  const distance = Math.sqrt(best.sq);
  const threshold = best.profile.matchThreshold;
  if (distance > threshold) return null;
  // Ambiguity guard.
  const second = Math.sqrt(secondSq);
  if (Number.isFinite(second) && second - distance < 0.05) return null;
  return { profile: best.profile, distance, second };
}

async function detect(
  frameId: number,
  bitmap: ImageBitmap,
  inputSize: number,
  withDescriptor: boolean,
): Promise<void> {
  if (!detectorReady) {
    post({ type: 'error', message: 'worker not initialised' });
    bitmap.close();
    return;
  }

  const t0 = performance.now();

  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    post({ type: 'error', message: 'OffscreenCanvas 2d context unavailable' });
    bitmap.close();
    return;
  }
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();

  const options = new faceapi.TinyFaceDetectorOptions({
    inputSize,
    scoreThreshold: 0.5,
  });

  // face-api accepts the OffscreenCanvas via duck-typing. The chained
  // `.withFaceLandmarks().withFaceDescriptors()` is what makes us spend
  // ~80-200 ms per frame on a Pi-class device; detection-only is ~30 ms.
  //
  // The result shape differs between paths: detection-only returns
  // `FaceDetection[]` (with `.box` + `.score`); the chained variant wraps
  // it in `{ detection, descriptor, landmarks }`. We normalise here.
  interface NormRow {
    box: { x: number; y: number; width: number; height: number };
    score: number;
    descriptor: Float32Array | null;
  }

  let normalised: NormRow[];
  if (withDescriptor && recognitionReady) {
    const raw = await faceapi
      .detectAllFaces(canvas as unknown as HTMLCanvasElement, options)
      .withFaceLandmarks()
      .withFaceDescriptors();
    normalised = raw.map((r) => ({
      box: {
        x: r.detection.box.x,
        y: r.detection.box.y,
        width: r.detection.box.width,
        height: r.detection.box.height,
      },
      score: r.detection.score,
      descriptor: r.descriptor as Float32Array,
    }));
  } else {
    const raw = await faceapi.detectAllFaces(
      canvas as unknown as HTMLCanvasElement,
      options,
    );
    normalised = raw.map((r) => ({
      box: { x: r.box.x, y: r.box.y, width: r.box.width, height: r.box.height },
      score: r.score,
      descriptor: null,
    }));
  }

  const transferables: Transferable[] = [];
  const out = normalised.map((r) => {
    let identity: ReturnType<typeof bestMatch> = null;
    if (r.descriptor && profiles.length > 0) {
      identity = bestMatch(r.descriptor);
    }
    if (r.descriptor) {
      // Transfer (don't copy) the 128 floats back to main.
      transferables.push(r.descriptor.buffer);
    }

    return {
      trackId: trackCounter++,
      box: r.box,
      score: r.score,
      descriptor: r.descriptor ?? undefined,
      identity: identity
        ? {
            profileId: identity.profile.profileId,
            displayName: identity.profile.displayName,
            isChild: identity.profile.isChild,
            distance: identity.distance,
          }
        : undefined,
    };
  });

  post(
    {
      type: 'detections',
      frameId,
      detections: out,
      durationMs: performance.now() - t0,
    },
    transferables,
  );
}

(self as unknown as Worker).addEventListener('message', (ev: MessageEvent<FaceWorkerIn>) => {
  const msg = ev.data;
  switch (msg.type) {
    case 'init':
      loadDetector(msg.modelsBaseUrl).catch((err) =>
        post({ type: 'error', message: `init failed: ${err?.message ?? String(err)}` }),
      );
      break;
    case 'loadRecognition':
      loadRecognition().catch((err) =>
        post({
          type: 'error',
          message: `loadRecognition failed: ${err?.message ?? String(err)}`,
        }),
      );
      break;
    case 'setProfiles':
      profiles = msg.profiles;
      post({ type: 'profilesLoaded', count: profiles.length });
      break;
    case 'detect':
      detect(msg.frameId, msg.bitmap, msg.inputSize, msg.withDescriptor).catch((err) =>
        post({ type: 'error', message: `detect failed: ${err?.message ?? String(err)}` }),
      );
      break;
    case 'shutdown':
      detectorReady = false;
      recognitionReady = false;
      profiles = [];
      break;
  }
});
