// Device-camera face recognition.
//
// When the Wall page loads on a device that has a camera (typically a
// front-facing kiosk tablet), we open the stream once, capture a frame
// every ~30s, and POST it to `/api/v1/wall/face-check`. On a known
// match the backend publishes `presence.known.arrived` on the family
// bus → the avatar reacts (`useWallEventStream` already handles it).
//
// We render a tiny status pill (camera on / off) so the family knows
// the kiosk is watching. No live preview — the Wall isn't a mirror.
//
// Privacy: the captured frame never leaves the LAN. The blob is JPEG
// at 320×240 (small enough not to be a privacy concern even if logs
// were ever spilled), and we keep the stream silent (no audio).

import { useEffect, useRef, useState } from 'react';

import { checkFaceFromDevice } from '../../api/wall';

const SAMPLE_INTERVAL_MS = 30_000;
const CAPTURE_W = 320;
const CAPTURE_H = 240;
const JPEG_QUALITY = 0.7;

type Phase = 'off' | 'asking' | 'on' | 'error';

export function WallDeviceCam() {
  const [phase, setPhase] = useState<Phase>('off');
  const [lastMatch, setLastMatch] = useState<string | null>(null);
  const [diag, setDiag] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const tickRef = useRef<number | null>(null);

  // Probe support up front. Only render the toggle when we actually
  // have a camera API. Note: navigator.mediaDevices is undefined on
  // insecure origins (HTTP without localhost) — Wall always runs over
  // HTTPS so we should be fine.
  const supportsMedia =
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia;

  useEffect(() => {
    return () => stopCamera();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function stopCamera() {
    if (tickRef.current) {
      window.clearInterval(tickRef.current);
      tickRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }

  async function startCamera() {
    setPhase('asking');
    setDiag(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: 640, height: 480 },
        audio: false,
      });
      streamRef.current = stream;
      const v = videoRef.current!;
      v.srcObject = stream;
      v.muted = true;
      v.playsInline = true;
      await v.play();
      setPhase('on');

      // First sample after the user permission grant lands; then
      // periodic.
      window.setTimeout(() => void captureAndCheck(), 2_000);
      tickRef.current = window.setInterval(
        () => void captureAndCheck(),
        SAMPLE_INTERVAL_MS,
      );
    } catch (e) {
      const err = e as DOMException;
      const msg = err?.name === 'NotAllowedError'
        ? 'Permesso telecamera negato'
        : err?.name === 'NotFoundError'
          ? 'Nessuna telecamera trovata'
          : `Errore camera: ${err?.message || err?.name || 'unknown'}`;
      setDiag(msg);
      setPhase('error');
    }
  }

  async function captureAndCheck() {
    const v = videoRef.current;
    if (!v || v.readyState < 2) return;
    const canvas = document.createElement('canvas');
    canvas.width = CAPTURE_W;
    canvas.height = CAPTURE_H;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(v, 0, 0, CAPTURE_W, CAPTURE_H);
    const blob: Blob | null = await new Promise((res) =>
      canvas.toBlob(res, 'image/jpeg', JPEG_QUALITY),
    );
    if (!blob) return;
    try {
      const out = await checkFaceFromDevice(blob);
      if (out.match?.name) {
        setLastMatch(out.match.name);
      } else if (out.found_face) {
        setLastMatch('volto sconosciuto');
      }
    } catch {
      // Best-effort. Silent failure is OK; the next tick retries.
    }
  }

  if (!supportsMedia) return null;

  return (
    <div className="flex items-center gap-2 select-none">
      {/* Hidden video element — we only render the status, not a live
          mirror feed. */}
      <video ref={videoRef} className="hidden" />
      {phase === 'off' || phase === 'asking' || phase === 'error' ? (
        <button
          type="button"
          onClick={startCamera}
          disabled={phase === 'asking'}
          className="inline-flex items-center gap-1.5 rounded-pill bg-surface2/80 hover:bg-surface2 text-fg-soft px-3 py-1.5 text-xs"
          title={
            phase === 'error'
              ? diag ?? 'Camera non disponibile'
              : 'Attiva camera del dispositivo per riconoscere chi è davanti'
          }
        >
          <span aria-hidden="true">📷</span>
          {phase === 'asking'
            ? 'Permesso…'
            : phase === 'error'
              ? 'Camera off'
              : 'Riconosci dal device'}
        </button>
      ) : (
        <button
          type="button"
          onClick={() => {
            stopCamera();
            setPhase('off');
            setLastMatch(null);
          }}
          className="inline-flex items-center gap-1.5 rounded-pill bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 px-3 py-1.5 text-xs"
          title="Spegni la camera del dispositivo"
        >
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          {lastMatch ? `Vedo: ${lastMatch}` : 'Camera attiva'}
        </button>
      )}
    </div>
  );
}
