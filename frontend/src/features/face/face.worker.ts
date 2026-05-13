/**
 * Face recognition Web Worker — Phase 1: detection only.
 *
 * Loads `tinyFaceDetector` from the same-origin models directory and
 * processes one ImageBitmap per `detect` message. Returns bounding boxes
 * and confidence scores. Descriptors + identity match arrive in Phase 2.
 *
 * The worker runs in its own thread so the main UI thread stays free for
 * the avatar render and video element. Heavy tensor work and the next
 * model loads will all live here.
 */

import * as faceapi from '@vladmandic/face-api';

import type { FaceWorkerIn, FaceWorkerOut } from './types';

let ready = false;
let trackCounter = 0;

const post = (msg: FaceWorkerOut) => (self as unknown as Worker).postMessage(msg);

async function loadModels(baseUrl: string): Promise<void> {
  // Phase 1: detector only. Landmark + recognition nets are lazy-loaded
  // in Phase 2 to keep the first-paint cheap (193 KB instead of 7 MB).
  await faceapi.nets.tinyFaceDetector.loadFromUri(baseUrl);
  ready = true;
  post({ type: 'ready', modelsLoaded: ['tinyFaceDetector'] });
}

async function detect(frameId: number, bitmap: ImageBitmap, inputSize: number): Promise<void> {
  if (!ready) {
    post({ type: 'error', message: 'worker not initialised' });
    bitmap.close();
    return;
  }

  const t0 = performance.now();

  // OffscreenCanvas keeps the bitmap GPU-side and avoids a CPU copy.
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

  // `detectAllFaces` on an OffscreenCanvas works because face-api ducktypes
  // on getContext / width / height — see vladmandic/face-api README.
  const results = await faceapi.detectAllFaces(canvas as unknown as HTMLCanvasElement, options);

  const detections = results.map((d) => ({
    trackId: trackCounter++,
    box: {
      x: d.box.x,
      y: d.box.y,
      width: d.box.width,
      height: d.box.height,
    },
    score: d.score,
  }));

  post({
    type: 'detections',
    frameId,
    detections,
    durationMs: performance.now() - t0,
  });
}

(self as unknown as Worker).addEventListener('message', (ev: MessageEvent<FaceWorkerIn>) => {
  const msg = ev.data;
  switch (msg.type) {
    case 'init':
      loadModels(msg.modelsBaseUrl).catch((err) =>
        post({ type: 'error', message: `init failed: ${err?.message ?? String(err)}` }),
      );
      break;
    case 'detect':
      detect(msg.frameId, msg.bitmap, msg.inputSize).catch((err) =>
        post({ type: 'error', message: `detect failed: ${err?.message ?? String(err)}` }),
      );
      break;
    case 'shutdown':
      ready = false;
      // Worker.terminate() in the parent reclaims everything; nothing
      // more to do here. Don't call into tfjs explicitly — the types
      // diverge between versions and we don't want a runtime crash on
      // teardown.
      break;
  }
});
