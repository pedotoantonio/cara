// Family sync — single shared WebSocket per browser tab.
//
// On login (or app load when already logged in), open `wss://.../api/v1/family/ws`
// with the JWT in the query string. Every event the server pushes
// triggers a callback that the React stores can subscribe to.
//
// Auto-reconnect with capped backoff. Heartbeat tolerance: server sends
// `ws.ping` every 30 s; if we don't hear anything for 90 s we consider
// the link dead and reopen.

import { getToken } from '../api/auth';

export interface FamilyEvent {
  kind: string;          // "task.created", "shopping.deleted", etc.
  user_id?: number | null;
  payload?: Record<string, unknown>;
}

type Listener = (ev: FamilyEvent) => void;

const _listeners = new Set<Listener>();
let _ws: WebSocket | null = null;
let _reconnectTimer: number | null = null;
let _watchdogTimer: number | null = null;
let _backoff = 1000;
let _lastSeen = 0;
let _intentionallyClosed = false;

function url(): string | null {
  const tok = getToken();
  if (!tok) return null;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/api/v1/family/ws?token=${encodeURIComponent(tok)}`;
}

function scheduleReconnect(): void {
  if (_intentionallyClosed) return;
  if (_reconnectTimer !== null) return;
  const delay = Math.min(_backoff, 30_000);
  _backoff = Math.min(_backoff * 2, 30_000);
  _reconnectTimer = window.setTimeout(() => {
    _reconnectTimer = null;
    open();
  }, delay);
}

function startWatchdog(): void {
  if (_watchdogTimer !== null) window.clearInterval(_watchdogTimer);
  _lastSeen = Date.now();
  _watchdogTimer = window.setInterval(() => {
    const idle = Date.now() - _lastSeen;
    if (idle > 90_000) {
      console.info('familySync: idle > 90s, reconnecting');
      try { _ws?.close(); } catch {/* */}
    }
  }, 15_000);
}

function open(): void {
  const u = url();
  if (!u) return;
  if (_ws && _ws.readyState <= 1) return;  // CONNECTING / OPEN
  _intentionallyClosed = false;

  let ws: WebSocket;
  try {
    ws = new WebSocket(u);
  } catch (err) {
    console.warn('familySync: open failed', err);
    scheduleReconnect();
    return;
  }
  _ws = ws;

  ws.addEventListener('open', () => {
    _backoff = 1000;
    startWatchdog();
  });

  ws.addEventListener('message', (ev) => {
    _lastSeen = Date.now();
    let data: FamilyEvent;
    try {
      data = JSON.parse(typeof ev.data === 'string' ? ev.data : '{}') as FamilyEvent;
    } catch {
      return;
    }
    if (!data.kind) return;
    // Skip housekeeping frames.
    if (data.kind === 'ws.hello' || data.kind === 'ws.ping') return;
    for (const l of _listeners) {
      try { l(data); } catch (err) { console.warn('familySync listener', err); }
    }
  });

  ws.addEventListener('close', () => {
    if (_watchdogTimer !== null) {
      window.clearInterval(_watchdogTimer);
      _watchdogTimer = null;
    }
    _ws = null;
    if (!_intentionallyClosed) scheduleReconnect();
  });

  ws.addEventListener('error', () => {
    // close handler will fire and reconnect.
  });
}

export function startFamilySync(): void {
  open();
}

export function stopFamilySync(): void {
  _intentionallyClosed = true;
  if (_reconnectTimer !== null) {
    window.clearTimeout(_reconnectTimer);
    _reconnectTimer = null;
  }
  if (_watchdogTimer !== null) {
    window.clearInterval(_watchdogTimer);
    _watchdogTimer = null;
  }
  try { _ws?.close(); } catch {/* */}
  _ws = null;
}

export function onFamilyEvent(listener: Listener): () => void {
  _listeners.add(listener);
  return () => { _listeners.delete(listener); };
}

// Auto-play voice greetings (presence.arrival / presence.unknown / etc.)
// pushed by the backend on `tts.play`. Set up once, on first import,
// so any open tab plays the audio without each route having to wire
// the handler. Suppressed when the tab is hidden.
let _ttsAutoplayBound = false;

function _bindTtsAutoplay() {
  if (_ttsAutoplayBound) return;
  _ttsAutoplayBound = true;
  onFamilyEvent((ev) => {
    if (ev.kind !== 'tts.play') return;
    const payload = (ev.payload ?? {}) as { audio_b64?: string; text?: string; kind?: string };
    if (!payload.audio_b64) return;
    if (typeof document !== 'undefined' && document.hidden) {
      // Tab hidden — skip autoplay (browser would block it anyway).
      return;
    }
    void import('./streamingAudio').then(({ startTurn, enqueueAudioChunk, endTurn }) => {
      startTurn();
      enqueueAudioChunk(payload.audio_b64!, {
        seq: 0,
        text: payload.text ?? '',
        voiceId: 'piper:greeting',
      });
      endTurn();
    });
  });
}

// Bind on module import — `familySync.ts` is imported during App boot
// for any authenticated user, so the listener is always live.
_bindTtsAutoplay();

/** Convenience helper: subscribe only to events whose `kind` starts with
 *  `prefix` (e.g. `useFamilyEvent("task.")` for task.created/updated/deleted). */
export function onFamilyEventPrefix(prefix: string, listener: Listener): () => void {
  return onFamilyEvent((ev) => {
    if (ev.kind.startsWith(prefix)) listener(ev);
  });
}
