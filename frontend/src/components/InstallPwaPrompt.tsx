/**
 * PWA install plumbing.
 *
 * Two surfaces:
 *
 * 1. **Floating banner** (`<InstallPwaPrompt />`) — appears once, after a
 *    delay, the first time CARA loads in a browser that supports install.
 *    The user can dismiss it permanently.
 *
 * 2. **Direct trigger** (`triggerInstall()` / `openInstallPrompt()`) —
 *    called by the "Installa CARA come app" entry in the bottom sheet.
 *    On Chromium it fires `beforeinstallprompt.prompt()` directly — no
 *    intermediate banner, the system dialog opens straight away. On iOS
 *    Safari (no programmatic API) we fall back to the share-sheet
 *    instructional banner. Everywhere else (Firefox, etc.) we show
 *    a one-shot manual-steps banner.
 *
 * The captured `beforeinstallprompt` event is held in module scope so a
 * click anywhere in the app can replay it without going through React
 * state.
 */

import { useEffect, useState } from 'react';

const DISMISSED_KEY = 'cara.pwa.install-dismissed.v1';
const NATIVE_DELAY_MS = 3000;
const FALLBACK_DELAY_MS = 8000;

export const OPEN_INSTALL_PROMPT_EVENT = 'cara:open-install-prompt';
const SHOW_FALLBACK_EVENT = 'cara:install-show-fallback';

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

type Mode = 'ios' | 'fallback' | 'auto-banner' | null;

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

// ── Module-scope event capture ─────────────────────────────────────
//
// Captures `beforeinstallprompt` on app load so any later click can
// trigger the install dialog without going through React state.

let _capturedEvent: BeforeInstallPromptEvent | null = null;
let _captureInstalled = false;

function ensureCapture() {
  if (_captureInstalled || typeof window === 'undefined') return;
  _captureInstalled = true;
  window.addEventListener('beforeinstallprompt', (e: Event) => {
    e.preventDefault();
    _capturedEvent = e as BeforeInstallPromptEvent;
  });
  window.addEventListener('appinstalled', () => {
    _capturedEvent = null;
    try {
      localStorage.setItem(DISMISSED_KEY, '1');
    } catch {
      // ignore
    }
  });
}

if (typeof window !== 'undefined') ensureCapture();

/**
 * Trigger the install flow. Chromium → fires the system dialog directly.
 * iOS Safari → opens the share-sheet instructional banner. Everywhere
 * else → opens a one-shot manual-steps banner. Returns a promise that
 * resolves to the outcome when known, `null` when fallback was shown.
 */
export async function triggerInstall(): Promise<'accepted' | 'dismissed' | null> {
  if (typeof window === 'undefined') return null;
  if (isStandalone()) return null;
  ensureCapture();

  if (_capturedEvent) {
    const ev = _capturedEvent;
    _capturedEvent = null;
    try {
      await ev.prompt();
      const choice = await ev.userChoice;
      if (choice.outcome === 'accepted') {
        try { localStorage.setItem(DISMISSED_KEY, '1'); } catch { /* ignore */ }
      }
      return choice.outcome;
    } catch {
      return null;
    }
  }

  // No captured event — fall back to the instructional banner so the
  // user still has a path forward (iOS, Firefox, hardened Chrome
  // without engagement heuristics, etc.).
  clearDismiss();
  window.dispatchEvent(new CustomEvent(SHOW_FALLBACK_EVENT));
  return null;
}

/** Backward-compat alias used by older callers. */
export function openInstallPrompt() {
  void triggerInstall();
}

// ── Auto-banner component ──────────────────────────────────────────
//
// Shows a passive prompt the first time CARA loads. The bottom-sheet
// "Installa" button is the proactive path; this is the discovery path
// for users who don't know they CAN install.

export function InstallPwaPrompt() {
  const [mode, setMode] = useState<Mode>(null);

  useEffect(() => {
    if (isStandalone()) return;
    ensureCapture();

    const dismissed = (() => {
      try {
        return Boolean(localStorage.getItem(DISMISSED_KEY));
      } catch {
        return false;
      }
    })();

    const browser = detectBrowser();
    let autoTimer: ReturnType<typeof setTimeout> | null = null;
    let fallbackTimer: ReturnType<typeof setTimeout> | null = null;

    if (!dismissed) {
      // Wait for the captured event before deciding which banner to show.
      autoTimer = setTimeout(() => {
        if (_capturedEvent) {
          setMode('auto-banner');
        } else if (browser.ios) {
          setMode('ios');
        }
      }, NATIVE_DELAY_MS);

      // Last-resort manual instructions for non-Chromium that never got
      // a `beforeinstallprompt` event.
      if (!browser.ios) {
        fallbackTimer = setTimeout(() => {
          setMode((current) => {
            if (current !== null) return current;
            if (_capturedEvent) return 'auto-banner';
            return 'fallback';
          });
        }, FALLBACK_DELAY_MS);
      }
    }

    // The bottom-sheet button can request the fallback banner when no
    // captured event is available (iOS / Firefox).
    const onForceFallback = () => {
      const browser2 = detectBrowser();
      setMode(browser2.ios ? 'ios' : 'fallback');
    };
    window.addEventListener(SHOW_FALLBACK_EVENT, onForceFallback);

    // Old API kept for backward compat (Settings button etc.) — same as
    // calling triggerInstall() directly.
    const onForceOpen = () => { void triggerInstall(); };
    window.addEventListener(OPEN_INSTALL_PROMPT_EVENT, onForceOpen);

    return () => {
      window.removeEventListener(SHOW_FALLBACK_EVENT, onForceFallback);
      window.removeEventListener(OPEN_INSTALL_PROMPT_EVENT, onForceOpen);
      if (autoTimer) clearTimeout(autoTimer);
      if (fallbackTimer) clearTimeout(fallbackTimer);
    };
  }, []);

  function dismissPermanent() {
    try {
      localStorage.setItem(DISMISSED_KEY, '1');
    } catch {
      // ignore
    }
    setMode(null);
  }

  function dismissOnce() {
    setMode(null);
  }

  if (mode === null) return null;

  const browser = detectBrowser();

  if (mode === 'auto-banner' && _capturedEvent) {
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
            onClick={async () => {
              setMode(null);
              await triggerInstall();
            }}
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
