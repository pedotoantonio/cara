/**
 * Floating banner that proposes installing CARA as a PWA.
 *
 * Path 1 — native (Chromium / Android Chrome / Edge / Brave): captures
 *   `beforeinstallprompt`, waits 3 s, shows banner with "Installa" that
 *   triggers the browser dialog.
 * Path 2 — iOS Safari: shows manual "Condividi → Aggiungi a Home"
 *   instructions (no programmatic install API on iOS).
 * Path 3 — fallback (any other browser, OR Chromium when the event
 *   never fires — e.g. self-signed cert, engagement heuristics not met):
 *   after 8 s shows browser-specific manual instructions so the user
 *   isn't left guessing how to install.
 *
 * Never shows when already running standalone. Dismissals persisted in
 * localStorage. The banner can also be re-opened on demand via the
 * `cara:open-install-prompt` window event (used by the Settings page).
 */

import { useEffect, useState } from 'react';

const DISMISSED_KEY = 'cara.pwa.install-dismissed.v1';
const NATIVE_DELAY_MS = 3000;
const FALLBACK_DELAY_MS = 8000;

export const OPEN_INSTALL_PROMPT_EVENT = 'cara:open-install-prompt';

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

type Mode = 'native' | 'ios' | 'fallback' | null;

interface BrowserHint {
  steps: string;
  shareIcon?: string;
}

function isStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  if (window.matchMedia?.('(display-mode: standalone)').matches) return true;
  return Boolean((window.navigator as { standalone?: boolean }).standalone);
}

function detectBrowser(): { ios: boolean; hint: BrowserHint } {
  const ua = typeof navigator !== 'undefined' ? navigator.userAgent || '' : '';
  const isIOS = /iPad|iPhone|iPod/.test(ua);
  const isMobileSafari = /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS|GSA/.test(ua);
  if (isIOS && isMobileSafari) {
    return {
      ios: true,
      hint: {
        steps: 'Tocca Condividi in basso, poi "Aggiungi a Home".',
        shareIcon: '⎙',
      },
    };
  }
  const isAndroid = /Android/.test(ua);
  if (isAndroid) {
    return {
      ios: false,
      hint: {
        steps: 'Apri il menu del browser (⋮) e tocca "Installa app" o "Aggiungi alla schermata Home".',
      },
    };
  }
  if (/Edg\//.test(ua)) {
    return {
      ios: false,
      hint: {
        steps: 'Clicca sull\'icona "Installa" nella barra degli indirizzi, oppure menu (⋯) → App → Installa CARA.',
      },
    };
  }
  if (/Firefox\//.test(ua)) {
    return {
      ios: false,
      hint: {
        steps: 'Firefox desktop non installa PWA nativamente. Aggiungi il sito ai segnalibri o usa Chrome/Edge per l\'installazione.',
      },
    };
  }
  // Chrome desktop / Brave / Vivaldi / Opera (Chromium-based).
  return {
    ios: false,
    hint: {
      steps: 'Clicca sull\'icona "Installa" nella barra degli indirizzi, oppure menu (⋮) → "Installa CARA".',
    },
  };
}

function clearDismiss() {
  try {
    localStorage.removeItem(DISMISSED_KEY);
  } catch {
    // ignore
  }
}

export function InstallPwaPrompt() {
  const [event, setEvent] = useState<BeforeInstallPromptEvent | null>(null);
  const [mode, setMode] = useState<Mode>(null);
  // When the user invoked it manually (Settings button), we ignore the
  // dismissed flag and the appearance delays.
  const [forced, setForced] = useState(false);

  useEffect(() => {
    if (isStandalone()) return;

    const dismissed = (() => {
      try {
        return Boolean(localStorage.getItem(DISMISSED_KEY));
      } catch {
        return false;
      }
    })();

    const browser = detectBrowser();

    let nativeTimer: ReturnType<typeof setTimeout> | null = null;
    let fallbackTimer: ReturnType<typeof setTimeout> | null = null;

    const onBeforeInstall = (e: Event) => {
      e.preventDefault();
      const ev = e as BeforeInstallPromptEvent;
      setEvent(ev);
      // Native available — cancel the manual fallback timer.
      if (fallbackTimer) {
        clearTimeout(fallbackTimer);
        fallbackTimer = null;
      }
      if (!dismissed && !forced) {
        nativeTimer = setTimeout(() => setMode('native'), NATIVE_DELAY_MS);
      }
    };
    window.addEventListener('beforeinstallprompt', onBeforeInstall);

    if (!dismissed && !forced) {
      if (browser.ios) {
        // iOS has no event — show the manual instructions after a delay.
        fallbackTimer = setTimeout(() => setMode('ios'), NATIVE_DELAY_MS);
      } else {
        // Desktop/Android non-iOS: if the event hasn't fired by FALLBACK_DELAY_MS,
        // we still surface the install path with manual instructions.
        fallbackTimer = setTimeout(() => {
          setMode((current) => (current === null ? 'fallback' : current));
        }, FALLBACK_DELAY_MS);
      }
    }

    const onInstalled = () => {
      try {
        localStorage.setItem(DISMISSED_KEY, '1');
      } catch {
        // ignore
      }
      setMode(null);
      setEvent(null);
      setForced(false);
    };
    window.addEventListener('appinstalled', onInstalled);

    const onForceOpen = () => {
      // Allow the Settings button to re-open the prompt regardless of
      // dismissal state, picking the best path available.
      clearDismiss();
      setForced(true);
      const browser2 = detectBrowser();
      if (event) {
        setMode('native');
      } else if (browser2.ios) {
        setMode('ios');
      } else {
        setMode('fallback');
      }
    };
    window.addEventListener(OPEN_INSTALL_PROMPT_EVENT, onForceOpen);

    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      window.removeEventListener('appinstalled', onInstalled);
      window.removeEventListener(OPEN_INSTALL_PROMPT_EVENT, onForceOpen);
      if (nativeTimer) clearTimeout(nativeTimer);
      if (fallbackTimer) clearTimeout(fallbackTimer);
    };
    // We intentionally re-bind when the captured event changes so the
    // forced-open handler can read the freshest event.
  }, [event, forced]);

  function dismissPermanent() {
    try {
      localStorage.setItem(DISMISSED_KEY, '1');
    } catch {
      // ignore
    }
    setMode(null);
    setForced(false);
  }

  function dismissOnce() {
    setMode(null);
    setForced(false);
  }

  async function triggerInstall() {
    if (!event) return;
    setMode(null);
    try {
      await event.prompt();
      const choice = await event.userChoice;
      if (choice.outcome === 'accepted') {
        dismissPermanent();
      }
    } catch {
      // user closed the system dialog quickly — treat as dismissed-for-now
    } finally {
      setEvent(null);
      setForced(false);
    }
  }

  if (mode === null) return null;

  const browser = detectBrowser();

  // Native install path — Chromium with `beforeinstallprompt` captured.
  if (mode === 'native' && event) {
    return (
      <Banner ariaLabel="Installa CARA come app" onClose={dismissPermanent}>
        <p className="text-sm font-medium">Installa CARA come app</p>
        <p className="text-xs text-slate-400 mt-0.5">
          Apri CARA dalla tua schermata Home, a tutto schermo, anche offline
          per le funzioni base.
        </p>
        <div className="flex gap-2 mt-2">
          <button
            type="button"
            onClick={triggerInstall}
            className="rounded-lg bg-emerald-600 hover:bg-emerald-500
                       px-3 py-1.5 text-xs font-medium"
          >
            Installa
          </button>
          <button
            type="button"
            onClick={dismissPermanent}
            className="rounded-lg bg-slate-700 hover:bg-slate-600
                       border border-slate-600 px-3 py-1.5 text-xs"
          >
            No grazie
          </button>
        </div>
      </Banner>
    );
  }

  // iOS Safari — manual "Add to Home Screen" instructions.
  if (mode === 'ios') {
    return (
      <Banner
        ariaLabel="Aggiungi CARA alla schermata Home"
        onClose={dismissPermanent}
      >
        <p className="text-sm font-medium">Aggiungi CARA alla schermata Home</p>
        <p className="text-xs text-slate-400 mt-0.5 leading-snug">
          Tocca il pulsante{' '}
          <span className="text-emerald-300">
            {browser.hint.shareIcon ?? '⎙'} Condividi
          </span>{' '}
          in basso, poi{' '}
          <span className="text-emerald-300">"Aggiungi a Home"</span>. Avrai
          CARA come app a tutto schermo.
        </p>
        <button
          type="button"
          onClick={dismissPermanent}
          className="mt-2 rounded-lg bg-slate-700 hover:bg-slate-600
                     border border-slate-600 px-3 py-1.5 text-xs"
        >
          Ho capito
        </button>
      </Banner>
    );
  }

  // Fallback — browser supports install but the event didn't fire (or
  // user clicked "Installa CARA" from Settings). Show manual steps.
  return (
    <Banner ariaLabel="Installa CARA come app" onClose={dismissOnce}>
      <p className="text-sm font-medium">Installa CARA come app</p>
      <p className="text-xs text-slate-400 mt-0.5 leading-snug">
        {browser.hint.steps}
      </p>
      <button
        type="button"
        onClick={dismissPermanent}
        className="mt-2 rounded-lg bg-slate-700 hover:bg-slate-600
                   border border-slate-600 px-3 py-1.5 text-xs"
      >
        Ho capito
      </button>
    </Banner>
  );
}

interface BannerProps {
  children: React.ReactNode;
  ariaLabel: string;
  onClose: () => void;
}

function Banner({ children, ariaLabel, onClose }: BannerProps) {
  return (
    <div
      role="dialog"
      aria-label={ariaLabel}
      className="fixed z-[60] bottom-4 left-1/2 -translate-x-1/2
                 md:left-auto md:right-4 md:translate-x-0
                 w-[min(22rem,calc(100vw-2rem))]
                 rounded-2xl bg-slate-800/95 border border-slate-700
                 shadow-2xl backdrop-blur p-3 flex items-start gap-3
                 text-slate-100 animate-[caraToastIn_240ms_ease-out]"
    >
      <span className="text-2xl leading-none">📲</span>
      <div className="flex-1 min-w-0">{children}</div>
      <button
        type="button"
        onClick={onClose}
        className="text-slate-400 hover:text-slate-100 text-base leading-none"
        aria-label="Chiudi"
      >
        ✕
      </button>
    </div>
  );
}

/** Open the install prompt on demand (Settings page). */
export function openInstallPrompt() {
  window.dispatchEvent(new CustomEvent(OPEN_INSTALL_PROMPT_EVENT));
}
