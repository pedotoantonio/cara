/**
 * Frame quality scoring for the enrollment wizard.
 *
 * Quality is the product of four 0..1 factors:
 *   - detectorScore       confidence from tinyFaceDetector
 *   - areaScore           face area as a fraction of the frame (>20% is ideal)
 *   - centeringScore      how close the face center is to the frame center
 *   - singularityScore    1.0 if a single face, 0 if multiple (multi-face
 *                         enrollment captures are ambiguous)
 *
 * A frame is "good enough" when quality ≥ 0.8. The wizard auto-captures
 * after 3 consecutive good-enough frames so we don't snap on a one-frame
 * fluke. See `useAutoCapture` for the consecutive-streak logic.
 */

import type { FaceDetection } from '../types';

export interface QualityResult {
  score: number;
  detectorScore: number;
  areaScore: number;
  centeringScore: number;
  singularityScore: number;
  /** Human-readable hint to surface in the UI when score < 0.8. */
  hint: string | null;
}

export interface FrameSize {
  width: number;
  height: number;
}

const IDEAL_AREA_RATIO = 0.2;
const MAX_OFFSET_RATIO = 0.35;

export function computeQuality(
  detections: FaceDetection[],
  frame: FrameSize,
): QualityResult {
  if (detections.length === 0) {
    return {
      score: 0,
      detectorScore: 0,
      areaScore: 0,
      centeringScore: 0,
      singularityScore: 0,
      hint: 'Nessun volto rilevato. Avvicinati alla camera.',
    };
  }

  if (detections.length > 1) {
    return {
      score: 0,
      detectorScore: 0,
      areaScore: 0,
      centeringScore: 0,
      singularityScore: 0,
      hint: 'Inquadra solo una persona per volta.',
    };
  }

  const d = detections[0];
  const frameArea = frame.width * frame.height;
  const faceArea = d.box.width * d.box.height;
  const areaRatio = faceArea / frameArea;

  const detectorScore = clamp01(d.score);

  // areaScore: 0 at <5% area, 1 at >=20% area, linear in between.
  const areaScore =
    areaRatio >= IDEAL_AREA_RATIO
      ? 1
      : Math.max(0, (areaRatio - 0.05) / (IDEAL_AREA_RATIO - 0.05));

  // centeringScore: 1 if face center is at frame center, 0 if at >35%
  // offset on either axis.
  const cx = d.box.x + d.box.width / 2;
  const cy = d.box.y + d.box.height / 2;
  const dx = Math.abs(cx - frame.width / 2) / (frame.width / 2);
  const dy = Math.abs(cy - frame.height / 2) / (frame.height / 2);
  const offset = Math.max(dx, dy);
  const centeringScore = Math.max(0, 1 - offset / MAX_OFFSET_RATIO);

  const singularityScore = 1;

  const score = detectorScore * areaScore * centeringScore * singularityScore;

  let hint: string | null = null;
  if (detectorScore < 0.6) hint = 'Illuminazione bassa o sguardo non centrato.';
  else if (areaScore < 0.5) hint = 'Avvicinati alla camera.';
  else if (centeringScore < 0.5) hint = 'Sposta la testa al centro dell’inquadratura.';
  else if (score < 0.8) hint = 'Resta fermo, sto mettendo a fuoco…';

  return { score, detectorScore, areaScore, centeringScore, singularityScore, hint };
}

function clamp01(n: number): number {
  if (Number.isNaN(n)) return 0;
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}
