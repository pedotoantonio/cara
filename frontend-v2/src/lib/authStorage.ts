// 3-tier storage: localStorage → sessionStorage → in-memory map.
// Ereditato dal pattern v1 risolvendo "login 200 OK ma token perso" su
// Safari ITP / iOS PWA standalone / private mode / storage full.
//
// API: getItem/setItem/removeItem — identica a Storage.
// Side effect: emette evento `cara:storage-degraded` su window quando si
// degrada a tier inferiore — la UI può mostrare un banner.

type Tier = 'localStorage' | 'sessionStorage' | 'memory';

const memoryStore = new Map<string, string>();
let currentTier: Tier = 'localStorage';
let degradedNotified = false;

function emitDegraded(reason: string) {
  if (degradedNotified) return;
  degradedNotified = true;
  try {
    window.dispatchEvent(
      new CustomEvent('cara:storage-degraded', { detail: { tier: currentTier, reason } }),
    );
  } catch {
    /* noop */
  }
}

function probeWrite(storage: Storage): boolean {
  const k = '__cara_probe__';
  try {
    storage.setItem(k, '1');
    const ok = storage.getItem(k) === '1';
    storage.removeItem(k);
    return ok;
  } catch {
    return false;
  }
}

function getStorage(): Storage | null {
  if (currentTier === 'localStorage') {
    try {
      if (probeWrite(window.localStorage)) return window.localStorage;
      currentTier = 'sessionStorage';
      emitDegraded('localStorage unavailable');
    } catch {
      currentTier = 'sessionStorage';
      emitDegraded('localStorage throws');
    }
  }
  if (currentTier === 'sessionStorage') {
    try {
      if (probeWrite(window.sessionStorage)) return window.sessionStorage;
      currentTier = 'memory';
      emitDegraded('sessionStorage unavailable');
    } catch {
      currentTier = 'memory';
      emitDegraded('sessionStorage throws');
    }
  }
  return null;
}

export function getItem(key: string): string | null {
  const s = getStorage();
  if (s) return s.getItem(key);
  return memoryStore.get(key) ?? null;
}

export function setItem(key: string, value: string): void {
  const s = getStorage();
  if (s) {
    try {
      s.setItem(key, value);
      // Verify the write actually persisted (private mode silently no-ops)
      if (s.getItem(key) !== value) {
        currentTier = currentTier === 'localStorage' ? 'sessionStorage' : 'memory';
        emitDegraded('write silent no-op');
        return setItem(key, value);
      }
      return;
    } catch {
      currentTier = currentTier === 'localStorage' ? 'sessionStorage' : 'memory';
      emitDegraded('write throws');
      return setItem(key, value);
    }
  }
  memoryStore.set(key, value);
}

export function removeItem(key: string): void {
  const s = getStorage();
  if (s) {
    try {
      s.removeItem(key);
    } catch {
      /* noop */
    }
  }
  memoryStore.delete(key);
}

export function currentStorageTier(): Tier {
  // Trigger probe
  getStorage();
  return currentTier;
}
