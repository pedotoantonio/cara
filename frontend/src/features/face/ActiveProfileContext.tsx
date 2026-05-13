/**
 * Active profile context — bridges the face recognition layer to the
 * rest of CARA.
 *
 * Subscribes to `face.identified` and `face.lost` from FaceContext and
 * exposes "who is CARA currently talking to" + the child-mode flag. The
 * rest of the app reads this via `useActiveProfile()`; it does NOT need
 * to know about the worker, descriptors, or temporal smoothing.
 *
 * Persistence: the active profile is mirrored to sessionStorage so a
 * page reload during a conversation keeps the right addressee (face
 * recognition restarts cold and takes ~3 frames to re-confirm).
 *
 * Side effects on the document root:
 *   - `data-cara-active-profile`     = profileId | (unset)
 *   - `data-cara-child-mode`         = "true" | (unset)
 *
 * CSS can hook on `html[data-cara-child-mode="true"]` to apply playful
 * accents; analytics can read the dataset directly.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { useFaceContext } from './FaceContext';
import type { FaceEvent, FaceIdentity } from './types';


const STORAGE_KEY = 'cara.face.active-profile';


export interface ActiveProfile {
  profileId: string;
  displayName: string;
  isChild: boolean;
  /** Other identified family members in the same scene. */
  companions: FaceIdentity[];
  /** When the identity was confirmed (epoch ms). */
  identifiedAt: number;
}


interface ActiveProfileApi {
  active: ActiveProfile | null;
  /** True when the active profile has `isChild=true`. CARA Core uses this
   *  to switch to the simplified dictionary, the softer voice, and the
   *  smart-home safety gate. Defaults to false when no one is identified. */
  childMode: boolean;
  /** Manually clear the active profile (e.g. user logs out). */
  clear: () => void;
}


const Ctx = createContext<ActiveProfileApi | null>(null);


function readSession(): ActiveProfile | null {
  if (typeof sessionStorage === 'undefined') return null;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ActiveProfile;
    if (
      typeof parsed?.profileId === 'string' &&
      typeof parsed?.displayName === 'string'
    ) {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}


function writeSession(p: ActiveProfile | null): void {
  if (typeof sessionStorage === 'undefined') return;
  try {
    if (p == null) sessionStorage.removeItem(STORAGE_KEY);
    else sessionStorage.setItem(STORAGE_KEY, JSON.stringify(p));
  } catch {
    // sessionStorage quota or private mode — fail silent.
  }
}


function applyDom(p: ActiveProfile | null): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (p == null) {
    delete root.dataset.caraActiveProfile;
    delete root.dataset.caraChildMode;
    return;
  }
  root.dataset.caraActiveProfile = p.profileId;
  if (p.isChild) {
    root.dataset.caraChildMode = 'true';
  } else {
    delete root.dataset.caraChildMode;
  }
}


export function ActiveProfileProvider({ children }: { children: ReactNode }) {
  const face = useFaceContext();
  const [active, setActive] = useState<ActiveProfile | null>(() => readSession());

  // Mirror session-restored state to the DOM on mount.
  useEffect(() => {
    applyDom(active);
  }, [active]);

  useEffect(() => {
    const unsubscribe = face.onEvent((event: FaceEvent) => {
      if (event.kind === 'face.identified') {
        const next: ActiveProfile = {
          profileId: event.profileId,
          displayName: event.displayName,
          isChild: event.isChild,
          companions: event.companions,
          identifiedAt: Date.now(),
        };
        setActive(next);
        writeSession(next);
        applyDom(next);
      } else if (event.kind === 'face.lost') {
        // Clear only if the *active* profile was the one lost. If another
        // family member walked away the primary may have stayed.
        setActive((prev) => {
          if (prev && event.profileId === prev.profileId) {
            writeSession(null);
            applyDom(null);
            return null;
          }
          return prev;
        });
      }
    });
    return unsubscribe;
  }, [face]);

  // Keep the active profile in sync with the *current* primarySubject
  // for the companion list updates (people walking in/out without the
  // primary changing don't fire `face.identified` again).
  useEffect(() => {
    if (!face.primarySubject) return;
    setActive((prev) => {
      if (!prev) return prev;
      if (prev.profileId !== face.primarySubject!.profileId) return prev;
      const sameLength = prev.companions.length === face.companions.length;
      const sameOrder =
        sameLength &&
        prev.companions.every(
          (c, i) => c.profileId === face.companions[i].profileId,
        );
      if (sameOrder) return prev;
      const next = { ...prev, companions: face.companions };
      writeSession(next);
      return next;
    });
  }, [face.primarySubject, face.companions]);

  const clear = useCallback(() => {
    setActive(null);
    writeSession(null);
    applyDom(null);
  }, []);

  const value = useMemo<ActiveProfileApi>(
    () => ({
      active,
      childMode: active?.isChild ?? false,
      clear,
    }),
    [active, clear],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}


/** Constant null-API used when no provider is mounted (e.g. routes
 *  rendered before the app shell wraps in <ActiveProfileProvider>).
 *  Keeps consumers a one-liner: `const { active } = useActiveProfile()`
 *  always works — they just see `active === null`. */
const NULL_API: ActiveProfileApi = {
  active: null,
  childMode: false,
  clear: () => undefined,
};

export function useActiveProfile(): ActiveProfileApi {
  return useContext(Ctx) ?? NULL_API;
}
