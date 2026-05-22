// Avatar store — Zustand. Sorgente di verità per l'avatar persistente.
//
// Ogni page può chiamare setAvatar() al mount per esprimere il suo stato.
// Il floating avatar legge da qui in ogni page; l'hero avatar (HubHome)
// legge da qui; l'inline avatar nella chat legge da qui.

import { create } from 'zustand';
import type { EnergyState, Emotion } from '@/components/avatar/CaraFace';
import type { AccentToken } from '@/design/tokens';

export type AvatarSize = 'hero' | 'floating' | 'inline' | 'micro';
export type AvatarPosture = 'attentive' | 'peeking' | 'resting';

export interface AvatarState {
  size: AvatarSize;
  energy: EnergyState;
  emotion: Emotion;
  posture: AvatarPosture;
  glowAccent: AccentToken;
  caption: string | null;
  speaking: boolean;
  pendingNotifications: number;
  /** Optional context label for telemetry/debug. */
  context: string | null;

  setAvatar: (next: Partial<Omit<AvatarState, 'setAvatar' | 'reset'>>) => void;
  reset: () => void;
}

const DEFAULT: Omit<AvatarState, 'setAvatar' | 'reset'> = {
  size: 'hero',
  energy: 'idle',
  emotion: 'neutral',
  posture: 'attentive',
  glowAccent: 'coral',
  caption: null,
  speaking: false,
  pendingNotifications: 0,
  context: null,
};

export const useAvatarStore = create<AvatarState>((set) => ({
  ...DEFAULT,
  setAvatar: (next) => set(next),
  reset: () => set(DEFAULT),
}));

/** Convenience hook con shallow comparator — meno re-render. */
export function useAvatarSlice<T>(selector: (s: AvatarState) => T): T {
  return useAvatarStore(selector);
}
