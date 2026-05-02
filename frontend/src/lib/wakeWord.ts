/**
 * Wake-word detector — listens passively for the user to say "CARA"
 * (or a configured phrase) and fires a callback. Best-effort only:
 *
 * - Browsers stop microphone capture when the tab loses focus, so the
 *   detector pauses in background and resumes when the page is visible.
 * - The Web Speech API does not expose audio levels, so we cannot do
 *   real low-power VAD; we run continuous-ish STT and look for the
 *   keyword in interim transcripts. To keep it reasonable we
 *   self-restart the recognizer when the engine ends a session.
 *
 * Privacy note: nothing is sent to the backend until the wake word
 * fires AND the foreground conversation hook decides to record. The
 * background recognizer runs entirely on-device (the browser's STT,
 * which on Apple platforms is local).
 */

import { startListening, sttAvailable, type ListenHandle } from './speech';

const DEFAULT_PHRASE = 'cara';

export interface WakeWordOptions {
  phrase?: string;
  /** Called when the wake word is detected. */
  onWake: (followUpText?: string) => void;
}

export interface WakeWordHandle {
  stop: () => void;
  pause: () => void;
  resume: () => void;
}

export function startWakeWord(opts: WakeWordOptions): WakeWordHandle | null {
  if (!sttAvailable()) return null;
  const phrase = (opts.phrase ?? DEFAULT_PHRASE).toLowerCase();

  let cancelled = false;
  let paused = false;
  let active: ListenHandle | null = null;

  function loop() {
    if (cancelled || paused) return;
    active = startListening({
      lang: 'it',
      interim: true,
      onText: (text, isFinal) => {
        const norm = text.toLowerCase();
        // Strip leading punctuation/whitespace so "cara, …" matches.
        const trimmed = norm.replace(/^[\s.,!?]+/, '');
        if (trimmed.startsWith(phrase)) {
          // Capture whatever follows the wake word as the question.
          const after = trimmed
            .slice(phrase.length)
            .replace(/^[\s.,!?]+/, '')
            .trim();
          // Stop background listener and hand off; the consumer hook will
          // start its own conversational STT if needed.
          if (active) {
            active.stop();
            active = null;
          }
          opts.onWake(after || undefined);
          return;
        }
        // If the keyword wasn't found and STT just produced a final result
        // without the wake word, ignore and let `onEnd` restart us.
        if (isFinal) {
          // no-op
        }
      },
      onEnd: () => {
        active = null;
        // The browser ends the recognizer on silence — restart so we keep
        // listening passively. Small delay to avoid hammering on errors.
        if (!cancelled && !paused) {
          setTimeout(loop, 300);
        }
      },
      onError: () => {
        active = null;
        // After permission errors, "no-speech" timeouts, etc. — back off and retry.
        if (!cancelled && !paused) {
          setTimeout(loop, 1500);
        }
      },
    });
    // If startListening returned null the API isn't available; bail out.
    if (active === null) cancelled = true;
  }

  loop();

  // Auto-pause when the tab is hidden (browsers freeze the mic anyway,
  // and we don't want a frozen recognizer fighting the resume).
  function onVisibility() {
    if (document.hidden) {
      paused = true;
      active?.stop();
      active = null;
    } else if (paused) {
      paused = false;
      loop();
    }
  }
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibility);
  }

  return {
    stop: () => {
      cancelled = true;
      active?.stop();
      active = null;
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', onVisibility);
      }
    },
    pause: () => {
      paused = true;
      active?.stop();
      active = null;
    },
    resume: () => {
      if (cancelled) return;
      paused = false;
      loop();
    },
  };
}
