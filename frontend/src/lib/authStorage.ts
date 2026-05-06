/**
 * Robust auth-token storage.
 *
 * `localStorage` is unreliable on the platforms we care about:
 * - Safari ITP / iOS: throws QuotaExceeded in third-party / lockdown mode.
 * - PWA standalone (iOS): occasionally clears the store between sessions.
 * - Browsers in "Strict tracking protection" or "private mode": setItem
 *   either no-ops silently or throws.
 * - Self-signed cert without trusted CA: some browsers downgrade the
 *   origin to "non-secure" and disable persistent storage.
 *
 * When `localStorage.setItem` is the silent path, the symptom Antonio
 * reported happens: login succeeds on the network (200 + token), but
 * on next page load `getToken()` returns null, App falls back to the
 * Login screen → infinite loop.
 *
 * This module wraps storage with a 3-tier fallback:
 *   1. localStorage (preferred — survives reloads)
 *   2. sessionStorage (survives within tab, lost on close)
 *   3. in-memory map (lost on reload, but at least the current tab works)
 *
 * The active tier is detected on first write. A diagnostic event
 * `cara:storage-degraded` fires when we drop below localStorage so
 * the UI can show a banner explaining the limitation.
 */

type StorageTier = 'local' | 'session' | 'memory';

const memoryStore = new Map<string, string>();
let activeTier: StorageTier | null = null;
let degradedReason: string | null = null;

function tryWrite(store: Storage, key: string, value: string): boolean {
  try {
    store.setItem(key, value);
    // Some browsers silently no-op in private mode; verify the write.
    return store.getItem(key) === value;
  } catch (err) {
    degradedReason = (err as Error).message || 'storage error';
    return false;
  }
}

function detectTier(): StorageTier {
  if (typeof window === 'undefined') return 'memory';
  // Probe localStorage first.
  const probe = `__cara_probe_${Date.now()}`;
  try {
    if (tryWrite(window.localStorage, probe, '1')) {
      window.localStorage.removeItem(probe);
      return 'local';
    }
  } catch {
    // ignore — fall through
  }
  // Then sessionStorage.
  try {
    if (tryWrite(window.sessionStorage, probe, '1')) {
      window.sessionStorage.removeItem(probe);
      return 'session';
    }
  } catch {
    // ignore
  }
  return 'memory';
}

function ensureTier(): StorageTier {
  if (activeTier) return activeTier;
  activeTier = detectTier();
  if (activeTier !== 'local' && typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('cara:storage-degraded', {
        detail: { tier: activeTier, reason: degradedReason },
      }),
    );
    // eslint-disable-next-line no-console
    console.warn(
      `[cara-auth] localStorage unavailable, using ${activeTier} fallback. ` +
        `Reason: ${degradedReason ?? 'unknown'}`,
    );
  }
  return activeTier;
}

export interface StorageStatus {
  tier: StorageTier;
  degraded: boolean;
  reason: string | null;
}

export function getStorageStatus(): StorageStatus {
  const tier = ensureTier();
  return {
    tier,
    degraded: tier !== 'local',
    reason: degradedReason,
  };
}

export function setItem(key: string, value: string): void {
  const tier = ensureTier();
  if (tier === 'local') {
    if (!tryWrite(window.localStorage, key, value)) {
      // Fall back at runtime if localStorage degraded after detection.
      activeTier = 'session';
      setItem(key, value);
      return;
    }
  } else if (tier === 'session') {
    if (!tryWrite(window.sessionStorage, key, value)) {
      activeTier = 'memory';
      memoryStore.set(key, value);
    }
  } else {
    memoryStore.set(key, value);
  }
}

export function getItem(key: string): string | null {
  const tier = ensureTier();
  if (tier === 'local') {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  }
  if (tier === 'session') {
    try {
      return window.sessionStorage.getItem(key);
    } catch {
      return null;
    }
  }
  return memoryStore.get(key) ?? null;
}

export function removeItem(key: string): void {
  const tier = ensureTier();
  if (tier === 'local') {
    try {
      window.localStorage.removeItem(key);
    } catch {
      /* ignore */
    }
    return;
  }
  if (tier === 'session') {
    try {
      window.sessionStorage.removeItem(key);
    } catch {
      /* ignore */
    }
    return;
  }
  memoryStore.delete(key);
}
