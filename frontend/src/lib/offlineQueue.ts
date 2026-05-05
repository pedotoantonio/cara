// Offline mutation queue.
//
// While the device is offline (or the backend is unreachable), the
// frontend's PATCH/POST/DELETE on tasks/shopping/notes are buffered
// in localStorage. When connectivity returns we replay the queue in
// FIFO order with a small batch delay between calls.
//
// Conflict policy: last-write-wins, server side. We don't try to
// reconcile local-vs-server divergence — if the user offline-edits
// a row that someone else changed online, the offline version
// overwrites on flush. Acceptable for a household use case.
//
// What goes into the queue: only writes that are user-explicit
// (tap a checkbox, edit a title). Reads are NOT queued — they
// just fail and the UI shows a stale snapshot.

import { authHeaders } from '../api/auth';

const STORAGE_KEY = 'cara.offlineQueue.v1';

interface QueuedRequest {
  id: string;
  method: 'POST' | 'PATCH' | 'DELETE';
  url: string;
  body?: string;
  contentType?: string;
  ts: number;
}

type Listener = (n: number) => void;

const _listeners = new Set<Listener>();

function readQueue(): QueuedRequest[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw) as unknown;
    return Array.isArray(arr) ? arr as QueuedRequest[] : [];
  } catch {
    return [];
  }
}

function writeQueue(q: QueuedRequest[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(q));
  } catch {
    // Quota exceeded — drop oldest until it fits.
    const trimmed = q.slice(-50);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
    } catch {/* */}
  }
  _listeners.forEach(l => { try { l(q.length); } catch {/* */} });
}

export function queueLength(): number {
  return readQueue().length;
}

export function onQueueChange(l: Listener): () => void {
  _listeners.add(l);
  return () => { _listeners.delete(l); };
}

/**
 * Enqueue a write request to be sent later. Returns immediately.
 * The body is serialized as a string so we can survive a page reload.
 */
export function enqueue(req: Omit<QueuedRequest, 'id' | 'ts'>): void {
  const q = readQueue();
  q.push({
    ...req,
    id: crypto.randomUUID(),
    ts: Date.now(),
  });
  writeQueue(q);
}

let _flushing = false;

/**
 * Try to flush the queue. Stops on the first failure (assumes still
 * offline). Caller is responsible for triggering this on `online`
 * event + on app start.
 */
export async function flushQueue(): Promise<{ sent: number; remaining: number }> {
  if (_flushing) return { sent: 0, remaining: queueLength() };
  _flushing = true;
  let sent = 0;
  try {
    while (true) {
      const q = readQueue();
      if (q.length === 0) break;
      const head = q[0];
      try {
        const resp = await fetch(head.url, {
          method: head.method,
          headers: {
            ...(head.contentType ? { 'Content-Type': head.contentType } : {}),
            ...authHeaders(),
          },
          body: head.body,
        });
        if (!resp.ok) {
          // Permanent client error → drop the item so we don't loop.
          if (resp.status >= 400 && resp.status < 500 && resp.status !== 429) {
            console.warn('offlineQueue: dropping permanent failure', head.url, resp.status);
            writeQueue(q.slice(1));
            continue;
          }
          // 5xx / network — assume backend down, stop flushing.
          break;
        }
      } catch {
        // Network error — still offline. Stop.
        break;
      }
      writeQueue(q.slice(1));
      sent++;
      // Small delay so a long queue doesn't hammer the backend.
      await new Promise(r => setTimeout(r, 80));
    }
  } finally {
    _flushing = false;
  }
  return { sent, remaining: queueLength() };
}

// ---------------------------------------------------------------------------
// Online detection
// ---------------------------------------------------------------------------

let _online = typeof navigator !== 'undefined' ? navigator.onLine : true;
const _onlineListeners = new Set<(online: boolean) => void>();

export function isOnline(): boolean {
  return _online;
}

export function onOnlineChange(l: (online: boolean) => void): () => void {
  _onlineListeners.add(l);
  return () => { _onlineListeners.delete(l); };
}

function setOnline(v: boolean): void {
  if (_online === v) return;
  _online = v;
  _onlineListeners.forEach(l => { try { l(v); } catch {/* */} });
  if (v) {
    // Came back — flush.
    void flushQueue();
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('online', () => setOnline(true));
  window.addEventListener('offline', () => setOnline(false));
}

// ---------------------------------------------------------------------------
// Wrapper: make a request that auto-queues when offline
// ---------------------------------------------------------------------------

/**
 * fetch wrapper for write requests. When offline OR the request fails
 * with a network error, queues the request and returns a synthetic
 * 202-style response so the UI can react optimistically.
 */
export async function offlineAwareWrite(
  url: string,
  init: { method: 'POST' | 'PATCH' | 'DELETE'; body?: string; contentType?: string },
): Promise<{ queued: boolean; status: number; body: string | null }> {
  if (!_online) {
    enqueue({ url, method: init.method, body: init.body, contentType: init.contentType });
    return { queued: true, status: 202, body: null };
  }
  try {
    const resp = await fetch(url, {
      method: init.method,
      headers: {
        ...(init.contentType ? { 'Content-Type': init.contentType } : {}),
        ...authHeaders(),
      },
      body: init.body,
    });
    const text = await resp.text();
    if (!resp.ok && resp.status >= 500) {
      // Treat 5xx as transient → queue and retry.
      enqueue({ url, method: init.method, body: init.body, contentType: init.contentType });
      return { queued: true, status: 202, body: null };
    }
    return { queued: false, status: resp.status, body: text };
  } catch {
    enqueue({ url, method: init.method, body: init.body, contentType: init.contentType });
    setOnline(false);
    return { queued: true, status: 202, body: null };
  }
}
