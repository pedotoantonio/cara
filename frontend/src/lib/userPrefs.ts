/** Tiny localStorage-backed preferences (UI-only, per-device). */

const KEY = 'cara.prefs';

export interface UserPrefs {
  voiceEnabled: boolean;
  voiceLang: 'it' | 'en';
  soundsEnabled: boolean;
  soundsVolume: number; // 0..1
  wakeWordEnabled: boolean;
}

const DEFAULTS: UserPrefs = {
  voiceEnabled: false,
  voiceLang: 'it',
  soundsEnabled: true,
  soundsVolume: 0.4,
  wakeWordEnabled: false,
};

export function loadPrefs(): UserPrefs {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return DEFAULTS;
  }
}

export function savePrefs(prefs: UserPrefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    // ignore
  }
}
