// Sequential WebAudio queue for sentence-streamed TTS chunks.
//
// Backend emits `audio_chunk` SSE events with base64-encoded WAV bytes.
// We decode each into an AudioBuffer and play them back-to-back so the
// listener experiences one continuous CARA voice — even though the
// frames arrive over multiple seconds.
//
// `enqueue` is fire-and-forget: it kicks off decode in the background
// and chains playback onto whatever's already queued. `clear` drops
// pending buffers and stops the current source (used when the user
// interrupts CARA mid-sentence).

interface ChunkInfo {
  seq: number;
  text: string;
  voiceId: string;
}

let _ctx: AudioContext | null = null;

function getCtx(): AudioContext {
  if (!_ctx) {
    const Ctor: typeof AudioContext =
      (window.AudioContext ?? (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext) as typeof AudioContext;
    _ctx = new Ctor();
  }
  return _ctx;
}

// Active source (so clear() can stop it). The `playing` field gates the
// "is anything in flight?" predicate consumers use to decide whether
// they still need to call the legacy `speak()` path on done.
interface QueueState {
  active: AudioBufferSourceNode | null;
  pending: Promise<void>;
  endsAt: number;            // AudioContext.currentTime where last queued
                              // buffer will finish; ensures back-to-back schedule.
  chunks: number;            // total chunks received this turn
  onEndTimer: number | null;  // setTimeout that calls onAllDone() when queue drains
  onAllDone: (() => void) | null;
}

const _state: QueueState = {
  active: null,
  pending: Promise.resolve(),
  endsAt: 0,
  chunks: 0,
  onEndTimer: null,
  onAllDone: null,
};

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  // Return a fresh ArrayBuffer (decodeAudioData mutates input on Safari).
  return bytes.buffer.slice(0);
}

/**
 * Reset state at the start of a new turn. Call this BEFORE you begin
 * receiving audio_chunk events for a new assistant reply.
 */
export function startTurn(onAllDone?: () => void): void {
  clear();
  _state.chunks = 0;
  _state.endsAt = 0;
  _state.onAllDone = onAllDone ?? null;
  _state.pending = Promise.resolve();
}

/** Append a base64 WAV chunk for sequential playback. Schedules
 *  decoding + playback; returns immediately. */
export function enqueueAudioChunk(b64: string, info: ChunkInfo): void {
  _state.chunks += 1;
  const ctx = getCtx();
  if (ctx.state === 'suspended') {
    void ctx.resume().catch(() => undefined);
  }

  // Cancel any pending "all-done" timer — more chunks coming.
  if (_state.onEndTimer !== null) {
    window.clearTimeout(_state.onEndTimer);
    _state.onEndTimer = null;
  }

  // Chain decode + schedule onto the existing pending promise so chunks
  // play in order even if a later chunk's decode finishes first.
  _state.pending = _state.pending.then(async () => {
    let buffer: AudioBuffer;
    try {
      const bytes = base64ToArrayBuffer(b64);
      buffer = await ctx.decodeAudioData(bytes);
    } catch (err) {
      console.warn('streamingAudio decode failed', info.seq, err);
      return;
    }

    // Schedule at endsAt or now, whichever is later.
    const startAt = Math.max(ctx.currentTime + 0.02, _state.endsAt);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.start(startAt);
    _state.endsAt = startAt + buffer.duration;
    _state.active = source;
    source.onended = () => {
      if (_state.active === source) _state.active = null;
    };
  }).catch((err) => {
    console.warn('streamingAudio playback failed', info.seq, err);
  });
}

/** Mark the stream as terminated. Schedules `onAllDone` to fire when
 *  the queue actually drains (the last buffer finishes playing). */
export function endTurn(): void {
  // After the last enqueue completes its decode + schedule, the endsAt
  // is final. We poll AudioContext.currentTime until we cross it.
  const onAllDone = _state.onAllDone;
  if (!onAllDone) return;
  const ctx = getCtx();
  const settle = () => {
    const remaining = Math.max(0, _state.endsAt - ctx.currentTime);
    if (remaining < 0.02) {
      _state.onAllDone = null;
      onAllDone();
      return;
    }
    _state.onEndTimer = window.setTimeout(settle, Math.min(500, remaining * 1000 + 30));
  };
  // Wait until all decodes scheduled so far have run.
  void _state.pending.then(settle);
}

/** Stop everything immediately (user interruption). */
export function clear(): void {
  if (_state.onEndTimer !== null) {
    window.clearTimeout(_state.onEndTimer);
    _state.onEndTimer = null;
  }
  if (_state.active) {
    try { _state.active.stop(); } catch {/* already stopped */}
    try { _state.active.disconnect(); } catch {/* */}
    _state.active = null;
  }
  _state.endsAt = 0;
  _state.onAllDone = null;
  _state.pending = Promise.resolve();
}

/** True if at least one chunk was enqueued this turn. The chat layer
 *  uses this to decide whether to call the legacy speak() on done. */
export function chunksReceived(): number {
  return _state.chunks;
}
