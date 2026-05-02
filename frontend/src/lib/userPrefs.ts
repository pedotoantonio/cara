/** Tiny localStorage-backed preferences (UI-only, per-device). */

const KEY = 'cara.prefs';

export type TTSEngine = 'piper' | 'browser';

export interface UserPrefs {
  voiceEnabled: boolean;
  voiceLang: 'it' | 'en';
  soundsEnabled: boolean;
  soundsVolume: number; // 0..1
  wakeWordEnabled: boolean;
  /** Which engine to use for CARA's voice. Piper = server-rendered (default,
   * coherent across devices). Browser = SpeechSynthesisUtterance (uses the
   * device's installed voices; on iPhone this is the premium "Paola"). */
  ttsEngine: TTSEngine;
}

const DEFAULTS: UserPrefs = {
  voiceEnabled: false,
  voiceLang: 'it',
  soundsEnabled: true,
  soundsVolume: 0.4,
  wakeWordEnabled: false,
  ttsEngine: 'piper',
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
