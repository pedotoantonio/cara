/**
 * Unit tests for the frame quality scorer.
 *
 * The function is pure: no DOM, no worker, no async. Tests drive
 * synthetic FaceDetection arrays through the scorer and assert the
 * decisive factor (detector score, area, centering, singularity)
 * dominates.
 */

import { describe, expect, it } from 'vitest';

import type { FaceDetection } from '../types';

import { computeQuality } from './quality';


const FRAME = { width: 480, height: 360 };


function makeDetection(
  partial: Partial<Omit<FaceDetection, 'box'>> & {
    box?: Partial<FaceDetection['box']>;
  } = {},
): FaceDetection {
  return {
    trackId: 0,
    score: 0.95,
    box: {
      x: 140,
      y: 90,
      width: 200,
      height: 180,
      ...(partial.box ?? {}),
    },
    ...partial,
  } as FaceDetection;
}


describe('computeQuality', () => {
  it('returns zero with a clear hint when no face is detected', () => {
    const q = computeQuality([], FRAME);
    expect(q.score).toBe(0);
    expect(q.hint).toMatch(/nessun volto/i);
  });

  it('returns zero with a "one at a time" hint on multiple faces', () => {
    const q = computeQuality(
      [
        makeDetection(),
        makeDetection({ box: { x: 10, y: 10, width: 100, height: 100 } }),
      ],
      FRAME,
    );
    expect(q.score).toBe(0);
    expect(q.hint).toMatch(/solo una persona/i);
  });

  it('passes the threshold for a centered, well-sized, confident face', () => {
    const q = computeQuality([makeDetection()], FRAME);
    // 200x180 box on a 480x360 frame = 20.8% area → areaScore 1
    // Centered (cx=240, cy=180 == frame center) → centeringScore 1
    // detector 0.95 → final = 0.95
    expect(q.score).toBeGreaterThanOrEqual(0.8);
    expect(q.hint).toBeNull();
  });

  it('punishes a tiny face (area below 5%)', () => {
    const q = computeQuality(
      [makeDetection({ box: { x: 220, y: 170, width: 30, height: 20 } })],
      FRAME,
    );
    expect(q.score).toBeLessThan(0.4);
    expect(q.areaScore).toBeLessThan(0.2);
    expect(q.hint).toMatch(/avvicinati|illuminazione|fermo/i);
  });

  it('punishes an off-center face', () => {
    // Push the face all the way to the top-left so the centroid offset
    // dominates everything else.
    const q = computeQuality(
      [makeDetection({ box: { x: 0, y: 0, width: 80, height: 80 } })],
      FRAME,
    );
    expect(q.centeringScore).toBeLessThan(0.6);
    expect(q.score).toBeLessThan(0.6);
  });

  it('clamps a NaN detector score to 0', () => {
    const q = computeQuality([makeDetection({ score: Number.NaN })], FRAME);
    expect(q.detectorScore).toBe(0);
    expect(q.score).toBe(0);
  });
});
