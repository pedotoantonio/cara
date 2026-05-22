// Permission state tracking — single source of truth per i 4 permessi.
//
// Risolve l'antipattern v1 di chiedere permessi "al volo" senza un onboarding.
// Qui:
// - probe via Permissions API quando disponibile
// - fallback a chiamate dirette (getUserMedia/Notification.requestPermission/...)
// - persiste stato user-choice in localStorage per non riprovare ogni volta

import { useEffect, useState, useCallback } from 'react';
import { getItem, setItem } from '@/lib/authStorage';

export type PermissionStatus = 'granted' | 'denied' | 'prompt' | 'unsupported';

export interface PermissionsState {
  mic: PermissionStatus;
  camera: PermissionStatus;
  notifications: PermissionStatus;
  geolocation: PermissionStatus;
}

const SKIP_KEY = 'cara.permissions.skipped';
const ASKED_KEY = 'cara.permissions.asked'; // 'true' dopo onboarding completato

function getSkippedSet(): Set<keyof PermissionsState> {
  try {
    const raw = getItem(SKIP_KEY);
    if (!raw) return new Set();
    return new Set(JSON.parse(raw));
  } catch {
    return new Set();
  }
}

function setSkippedSet(s: Set<keyof PermissionsState>) {
  setItem(SKIP_KEY, JSON.stringify(Array.from(s)));
}

export function hasCompletedOnboarding(): boolean {
  return getItem(ASKED_KEY) === 'true';
}

export function markOnboardingComplete() {
  setItem(ASKED_KEY, 'true');
}

async function probe(name: 'microphone' | 'camera' | 'notifications' | 'geolocation'): Promise<PermissionStatus> {
  try {
    const api = (navigator as Navigator).permissions;
    if (!api?.query) {
      // Best-effort fallback
      if (name === 'notifications' && 'Notification' in window) {
        const p = Notification.permission;
        if (p === 'granted') return 'granted';
        if (p === 'denied') return 'denied';
        return 'prompt';
      }
      return 'unsupported';
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const r = await api.query({ name: name as any });
    return (r.state as PermissionStatus) ?? 'prompt';
  } catch {
    return 'unsupported';
  }
}

export function usePermissionsState() {
  const [state, setState] = useState<PermissionsState>({
    mic: 'unsupported',
    camera: 'unsupported',
    notifications: 'unsupported',
    geolocation: 'unsupported',
  });

  const refresh = useCallback(async () => {
    const [mic, camera, notifications, geolocation] = await Promise.all([
      probe('microphone'),
      probe('camera'),
      probe('notifications'),
      probe('geolocation'),
    ]);
    setState({ mic, camera, notifications, geolocation });
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { state, refresh };
}

// Funzioni di richiesta permessi — chiamate dall'onboarding o "just-in-time"
// quando una feature ne ha bisogno.

export async function requestMic(): Promise<PermissionStatus> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop());
    return 'granted';
  } catch (err) {
    const name = (err as Error)?.name;
    if (name === 'NotAllowedError') return 'denied';
    if (name === 'NotFoundError') return 'unsupported';
    return 'denied';
  }
}

export async function requestCamera(): Promise<PermissionStatus> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
    stream.getTracks().forEach((t) => t.stop());
    return 'granted';
  } catch (err) {
    const name = (err as Error)?.name;
    if (name === 'NotAllowedError') return 'denied';
    if (name === 'NotFoundError') return 'unsupported';
    return 'denied';
  }
}

export async function requestNotifications(): Promise<PermissionStatus> {
  if (!('Notification' in window)) return 'unsupported';
  try {
    const r = await Notification.requestPermission();
    if (r === 'granted') return 'granted';
    if (r === 'denied') return 'denied';
    return 'prompt';
  } catch {
    return 'denied';
  }
}

export async function requestGeolocation(): Promise<PermissionStatus> {
  if (!('geolocation' in navigator)) return 'unsupported';
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      () => resolve('granted'),
      (err) => {
        if (err.code === err.PERMISSION_DENIED) resolve('denied');
        else resolve('prompt');
      },
      { timeout: 8000 },
    );
  });
}

export function skipPermission(key: keyof PermissionsState) {
  const s = getSkippedSet();
  s.add(key);
  setSkippedSet(s);
}

export function unskipPermission(key: keyof PermissionsState) {
  const s = getSkippedSet();
  s.delete(key);
  setSkippedSet(s);
}

export function isSkipped(key: keyof PermissionsState): boolean {
  return getSkippedSet().has(key);
}
