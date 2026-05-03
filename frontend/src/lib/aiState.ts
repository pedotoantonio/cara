/**
 * Global AI activity state — a tiny pub/sub singleton that any component
 * can read, any code path can write. Mirrors Lumo's LED state machine
 * idea (the LED ring shows what the AI is doing right now), adapted to
 * the PWA: a single floating banner consumes this state and renders an
 * ambient indicator visible on ANY page.
 *
 * Phases:
 *   - idle:       nothing in flight
 *   - listening:  STT is capturing audio
 *   - thinking:   chat stream is producing tokens
 *   - speaking:   TTS is playing back a reply
 */

export type AiPhase = 'idle' | 'listening' | 'thinking' | 'speaking';

let _phase: AiPhase = 'idle';
const _listeners = new Set<(p: AiPhase) => void>();

export function getAiPhase(): AiPhase {
  return _phase;
}

export function setAiPhase(p: AiPhase): void {
  if (_phase === p) return;
  _phase = p;
  for (const fn of _listeners) fn(p);
}

export function subscribeAiPhase(fn: (p: AiPhase) => void): () => void {
  _listeners.add(fn);
  return () => {
    _listeners.delete(fn);
  };
}
