// TTS playback queue per `audio_chunk` SSE events.
//
// Il backend emette chunk WAV base64 mentre l'LLM produce frasi (Piper
// TTS server-side). Noi li accodiamo e li riproduciamo in ordine, evitando
// gap audio fra chunk consecutivi.
//
// Approccio: per ogni chunk creiamo un <audio> Element con src = data URL,
// e quando l'attuale finisce partiamo col successivo. Niente AudioContext
// complesso — supporto universale, latency minimo, niente ricodifica.

import type { ChatAudioChunkPayload } from './chatStream';

interface QueuedChunk {
  audio: HTMLAudioElement;
  final: boolean;
}

export interface TtsPlayer {
  enqueue: (chunk: ChatAudioChunkPayload) => void;
  /** Stop playback and clear queue (per user interrupt). */
  stop: () => void;
  /** Currently playing? */
  isPlaying: () => boolean;
  /** Register a callback fired when last chunk ends. */
  onComplete: (cb: () => void) => void;
}

export function createTtsPlayer(): TtsPlayer {
  const queue: QueuedChunk[] = [];
  let playing: HTMLAudioElement | null = null;
  let completeCb: (() => void) | null = null;

  function playNext() {
    if (playing) return;
    const next = queue.shift();
    if (!next) {
      // Queue drained
      if (completeCb) completeCb();
      return;
    }
    playing = next.audio;
    playing.onended = () => {
      playing = null;
      playNext();
    };
    playing.onerror = () => {
      console.warn('[tts] chunk playback error', playing?.error);
      playing = null;
      playNext();
    };
    void playing.play().catch((err) => {
      // Autoplay block — first user gesture not registered. Caller must
      // ensure first enqueue happens inside a user-initiated event handler.
      console.warn('[tts] play() rejected', err);
      playing = null;
      playNext();
    });
  }

  return {
    enqueue(chunk) {
      const dataUrl = `data:${chunk.mime};base64,${chunk.audio}`;
      const el = new Audio(dataUrl);
      el.preload = 'auto';
      queue.push({ audio: el, final: !!chunk.final });
      playNext();
    },
    stop() {
      queue.length = 0;
      if (playing) {
        try {
          playing.pause();
          playing.src = '';
        } catch {
          /* noop */
        }
        playing = null;
      }
    },
    isPlaying() {
      return playing !== null;
    },
    onComplete(cb) {
      completeCb = cb;
    },
  };
}
