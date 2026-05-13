/**
 * SVG overlay drawn on top of a <video> element.
 *
 * Phase 1: bounding boxes only. Identity labels show up from Phase 2 when
 * `detection.identity` is filled by the recognition pipeline.
 *
 * Caller is responsible for positioning the overlay above the video with
 * the same dimensions (e.g. wrap both in a `position: relative` div).
 */

import { useFaceContext } from '../FaceContext';
import type { FaceDetection } from '../types';

interface Props {
  /** Source frame width as sent to the worker (post-downscale). */
  sourceWidth: number;
  /** Source frame height as sent to the worker (post-downscale). */
  sourceHeight: number;
  /** Rendered width (CSS px). */
  width: number;
  /** Rendered height (CSS px). */
  height: number;
  /** Hide when no faces (default true). */
  hideWhenEmpty?: boolean;
}

function boxColor(d: FaceDetection): string {
  if (d.identity) return '#22c55e'; // green-500 when matched
  if (d.score >= 0.8) return '#fbbf24'; // amber-400 confident unknown
  return '#94a3b8'; // slate-400 low-confidence
}

export function FaceOverlay({
  sourceWidth,
  sourceHeight,
  width,
  height,
  hideWhenEmpty = true,
}: Props) {
  const { detections } = useFaceContext();
  if (hideWhenEmpty && detections.length === 0) return null;

  const sx = width / sourceWidth;
  const sy = height / sourceHeight;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
      aria-hidden
    >
      {detections.map((d) => {
        const x = d.box.x * sx;
        const y = d.box.y * sy;
        const w = d.box.width * sx;
        const h = d.box.height * sy;
        const color = boxColor(d);
        const label = d.identity
          ? `${d.identity.displayName} · ${d.identity.distance.toFixed(2)}`
          : `face · ${Math.round(d.score * 100)}%`;
        return (
          <g key={d.trackId}>
            <rect
              x={x}
              y={y}
              width={w}
              height={h}
              fill="none"
              stroke={color}
              strokeWidth={2}
              rx={6}
            />
            <rect
              x={x}
              y={Math.max(0, y - 18)}
              width={Math.max(60, label.length * 6.5)}
              height={16}
              fill={color}
              opacity={0.85}
              rx={4}
            />
            <text
              x={x + 4}
              y={Math.max(12, y - 6)}
              fontSize={11}
              fontFamily="ui-sans-serif, system-ui, sans-serif"
              fill="#0f172a"
            >
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
