/**
 * Capture step — runs the webcam, watches quality, auto-snaps after
 * `AUTO_CAPTURE_STREAK` consecutive frames at quality ≥ 0.8.
 *
 * Reused for every angle (front / left / right / smile / neutral); the
 * caller passes a `prompt` describing what to ask the user to do. The
 * step is dumb: it doesn't know what angle is "next", that's the
 * wizard's job.
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { FaceOverlay } from '../components/FaceOverlay';
import { useFaceContext } from '../FaceContext';

import { computeQuality, type QualityResult } from './quality';
import {
  AUTO_CAPTURE_STREAK,
  QUALITY_THRESHOLD,
  type WizardCapture,
} from './types';


export interface CapturePrompt {
  angle: WizardCapture['angle'];
  title: string;
  instruction: string;
}

interface Props {
  prompt: CapturePrompt;
  /** How many captures have already been collected (1-indexed display). */
  completed: number;
  total: number;
  onCaptured: (c: WizardCapture) => void;
}

const RENDER_WIDTH = 480;
const RENDER_HEIGHT = 360;
const SOURCE_WIDTH = 480;
const SOURCE_HEIGHT = 360;

export function CaptureStep({ prompt, completed, total, onCaptured }: Props) {
  const face = useFaceContext();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const [mediaError, setMediaError] = useState<string | null>(null);
  const streakRef = useRef(0);
  // Whether we've already fired onCaptured for this mount — guards the
  // auto-capture trigger from firing twice on a slow re-render.
  const firedRef = useRef(false);

  // Acquire webcam once per mount; release on unmount so the indicator
  // light goes off the moment the wizard moves on or unmounts.
  useEffect(() => {
    let cancelled = false;
    streakRef.current = 0;
    firedRef.current = false;

    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: 640 },
            height: { ideal: 480 },
            facingMode: 'user',
          },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          await video.play().catch(() => undefined);
          face.start(video);
        }
      } catch (err) {
        setMediaError(
          err instanceof DOMException && err.name === 'NotAllowedError'
            ? 'Permesso camera negato. Concedi l’accesso dalla barra del browser.'
            : err instanceof DOMException && err.name === 'NotFoundError'
              ? 'Nessuna camera trovata sul dispositivo.'
              : err instanceof Error
                ? err.message
                : String(err),
        );
      }
    })();

    return () => {
      cancelled = true;
      face.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
    // We intentionally only react to a fresh mount of the step. The
    // FaceContext stop/start dance happens once per angle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prompt.angle]);

  const quality = useMemo<QualityResult>(
    () => computeQuality(face.detections, { width: SOURCE_WIDTH, height: SOURCE_HEIGHT }),
    [face.detections],
  );

  // Auto-capture: streak counter on quality + recognitionReady. A single
  // good frame is not enough — we want a stable pose.
  useEffect(() => {
    if (firedRef.current) return;
    if (!face.recognitionReady) return;
    if (quality.score >= QUALITY_THRESHOLD) {
      streakRef.current += 1;
    } else {
      streakRef.current = 0;
    }

    if (streakRef.current >= AUTO_CAPTURE_STREAK) {
      // Pull the descriptor of the (single) detection from the worker payload.
      const d = face.detections[0];
      if (d?.descriptor) {
        firedRef.current = true;
        onCaptured({
          angle: prompt.angle,
          descriptor: Array.from(d.descriptor),
          quality: quality.score,
        });
      } else {
        // Descriptor missing — recognition net probably not ready yet.
        streakRef.current = 0;
      }
    }
  }, [quality.score, face.recognitionReady, face.detections, onCaptured, prompt.angle]);

  const progress = Math.min(1, streakRef.current / AUTO_CAPTURE_STREAK);

  return (
    <div className="bg-white rounded-2xl shadow-sm border p-6">
      <div className="mb-4">
        <div className="text-sm text-slate-500">
          Acquisizione {completed + 1} di {total}
        </div>
        <h2 className="text-2xl font-semibold">{prompt.title}</h2>
        <p className="text-slate-600 mt-1">{prompt.instruction}</p>
      </div>

      <div
        className="relative mx-auto bg-slate-900 rounded-xl overflow-hidden"
        style={{ width: RENDER_WIDTH, height: RENDER_HEIGHT }}
      >
        <video
          ref={videoRef}
          width={RENDER_WIDTH}
          height={RENDER_HEIGHT}
          autoPlay
          muted
          playsInline
          className="w-full h-full object-cover"
        />
        <FaceOverlay
          sourceWidth={SOURCE_WIDTH}
          sourceHeight={SOURCE_HEIGHT}
          width={RENDER_WIDTH}
          height={RENDER_HEIGHT}
          hideWhenEmpty={false}
        />

        {/* Capture progress ring overlay */}
        <ProgressRing progress={progress} />

        {mediaError && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-900/80 text-white text-center p-6">
            <div>
              <p className="font-medium mb-2">Camera non disponibile</p>
              <p className="text-sm text-slate-300">{mediaError}</p>
            </div>
          </div>
        )}
      </div>

      <div className="mt-4 min-h-[2.5rem]">
        {!face.recognitionReady ? (
          <p className="text-sm text-slate-500">
            Caricamento dei modelli di riconoscimento (~7 MB)…
          </p>
        ) : quality.hint ? (
          <p className="text-sm text-amber-700">{quality.hint}</p>
        ) : (
          <p className="text-sm text-emerald-700">
            Qualità del frame {(quality.score * 100).toFixed(0)}% — resta fermo.
          </p>
        )}
      </div>
    </div>
  );
}


function ProgressRing({ progress }: { progress: number }) {
  // 0..1 → SVG ring closing. We draw it dim by default and bright as
  // it fills so the user sees momentum even before reaching 100%.
  const size = 88;
  const stroke = 6;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - progress);
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="absolute top-3 right-3 pointer-events-none"
      aria-hidden
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="rgba(255,255,255,0.25)"
        strokeWidth={stroke}
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="#10b981"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={dashOffset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: 'stroke-dashoffset 200ms ease-out' }}
      />
    </svg>
  );
}
