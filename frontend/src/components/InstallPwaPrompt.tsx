/**
 * Floating banner that proposes installing CARA as a PWA.
 *
 * Behaviour:
 *   - Chrome / Edge / Android: listens for `beforeinstallprompt`, shows a
 *     small dismissible banner ~6 s after the page loaded if the event
 *     fired, and on click triggers the native install flow.
 *   - iOS Safari (no programmatic install): if the page is being viewed
 *     in regular Safari (not yet installed), shows manual instructions
 *     ("tocca Condividi ↑ → Aggiungi a schermata Home").
 *   - Never shows when already running standalone (display-mode: standalone
 *     or `navigator.standalone === true` on iOS).
 *   - Dismissals are remembered in localStorage so we don't pester the
 *     user. "Installa" succeeded → permanently dismissed; "No grazie" or
 *     iOS dismiss → also permanently dismissed.
 */

import { useEffect, useState } from 'react';

const DISMISSED_KEY = 'cara.pwa.install-dismissed.v1';
const APPEAR_DELAY_MS = 6000;

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

function isStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  if (window.matchMedia?.('(display-mode: standalone)').matches) return true;
  return Boolean(
    (window.navigator as { standalone?: boolean }).standalone,
  );
}

function isIOSSafari(): boolean {
  if (typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent || '';
  const isIOS = /iPad|iPhone|iPod/.test(ua);
  // Exclude in-app webviews and other-browser apps on iOS — only true
  // mobile Safari can do "Add to Home Screen" with the share sheet.
  const isMobileSafari = /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS|GSA/.test(ua);
  return isIOS && isMobileSafari;
}

export function InstallPwaPrompt() {
  const [event, setEvent] = useState<BeforeInstallPromptEvent | null>(null);
  const [chromeShow, setChromeShow] = useState(false);
  const [iosShow, setIosShow] = useState(false);

  useEffect(() => {
    if (isStandalone()) return;
    try {
      if (localStorage.getItem(DISMISSED_KEY)) return;
    } catch {
      // localStorage blocked: just don't remember dismissals
    }

    const onBeforeInstall = (e: Event) => {
      e.preventDefault();
      setEvent(e as BeforeInstallPromptEvent);
    };
    window.addEventListener('beforeinstallprompt', onBeforeInstall);

    let iosTimer: ReturnType<typeof setTimeout> | null = null;
    if (isIOSSafari()) {
      iosTimer = setTimeout(() => setIosShow(true), APPEAR_DELAY_MS);
    }

    const onInstalled = () => {
      try {
        localStorage.setItem(DISMISSED_KEY, '1');
      } catch {
        // ignore
      }
      setChromeShow(false);
      setIosShow(false);
      setEvent(null);
    };
    window.addEventListener('appinstalled', onInstalled);

    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      window.removeEventListener('appinstalled', onInstalled);
      if (iosTimer) clearTimeout(iosTimer);
    };
  }, []);

  // Once the install event has been captured, wait a few seconds before
  // showing the banner so we don't interrupt the very first interaction.
  useEffect(() => {
    if (!event) return;
    const t = setTimeout(() => setChromeShow(true), APPEAR_DELAY_MS);
    return () => clearTimeout(t);
  }, [event]);

  function dismissPermanent() {
    try {
      localStorage.setItem(DISMISSED_KEY, '1');
    } catch {
      // ignore
    }
    setChromeShow(false);
    setIosShow(false);
  }

  async function triggerInstall() {
    if (!event) return;
    setChromeShow(false);
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
    }
  }

  if (chromeShow && event) {
    return (
      <div
        role="dialog"
        aria-label="Installa CARA come app"
        className="fixed z-[60] bottom-4 left-1/2 -translate-x-1/2
                   md:left-auto md:right-4 md:translate-x-0
                   w-[min(22rem,calc(100vw-2rem))]
                   rounded-2xl bg-slate-800/95 border border-slate-700
                   shadow-2xl backdrop-blur p-3 flex items-start gap-3
                   text-slate-100 animate-[caraToastIn_240ms_ease-out]"
      >
        <span className="text-2xl leading-none">📲</span>
        <div className="flex-1 min-w-0">
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
        </div>
        <button
          type="button"
          onClick={dismissPermanent}
          className="text-slate-400 hover:text-slate-100 text-base leading-none"
          aria-label="Chiudi"
        >
          ✕
        </button>
      </div>
    );
  }

  if (iosShow) {
    return (
      <div
        role="dialog"
        aria-label="Aggiungi CARA alla schermata Home"
        className="fixed z-[60] bottom-4 left-1/2 -translate-x-1/2
                   w-[min(22rem,calc(100vw-2rem))]
                   rounded-2xl bg-slate-800/95 border border-slate-700
                   shadow-2xl backdrop-blur p-3 flex items-start gap-3
                   text-slate-100 animate-[caraToastIn_240ms_ease-out]"
      >
        <span className="text-2xl leading-none">📲</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium">Aggiungi CARA alla schermata Home</p>
          <p className="text-xs text-slate-400 mt-0.5 leading-snug">
            Tocca il pulsante <span className="text-emerald-300">⎙ Condividi</span>{' '}
            in basso, poi <span className="text-emerald-300">"Aggiungi a Home"</span>.
            Avrai CARA come app a tutto schermo.
          </p>
          <button
            type="button"
            onClick={dismissPermanent}
            className="mt-2 rounded-lg bg-slate-700 hover:bg-slate-600
                       border border-slate-600 px-3 py-1.5 text-xs"
          >
            Ho capito
          </button>
        </div>
        <button
          type="button"
          onClick={dismissPermanent}
          className="text-slate-400 hover:text-slate-100 text-base leading-none"
          aria-label="Chiudi"
        >
          ✕
        </button>
      </div>
    );
  }

  return null;
}
