/**
 * Wire a <video> element to the face detection worker for the lifetime
 * of the consumer component. Use from any surface that wants live
 * face detection (Wall, settings preview, enrollment wizard).
 *
 * Usage:
 *
 *     const videoRef = useRef<HTMLVideoElement>(null);
 *     useFaceDetection(videoRef, { enabled: true });
 */

import { useEffect, type RefObject } from 'react';

import { useFaceContext } from '../FaceContext';

interface Options {
  /** When false, the loop is stopped (used as the privacy kill-switch). */
  enabled: boolean;
}

export function useFaceDetection(
  videoRef: RefObject<HTMLVideoElement | null>,
  { enabled }: Options,
) {
  const { start, stop } = useFaceContext();

  useEffect(() => {
    if (!enabled) {
      stop();
      return;
    }
    const video = videoRef.current;
    if (!video) return;
    start(video);
    return () => stop();
  }, [enabled, videoRef, start, stop]);
}
