// V2 migration banner — non-intrusive pill in v1 to discover v2.
//
// Da includere in AppShell.tsx sopra il TopBar (o sotto) quando si
// vuole iniziare la fase A della migrazione (vedi
// docs/pwa-migration-playbook.md). Persistente nel localStorage,
// re-mostra dopo 7 giorni.

import { useEffect, useState } from 'react';

const STORAGE_KEY = 'cara.v2_banner.dismissed_at';
const RE_SHOW_AFTER_DAYS = 7;
const V2_URL = 'https://192.168.1.23:8456/';

function shouldShow(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return true;
    const dismissed = new Date(raw).getTime();
    const now = Date.now();
    const daysAgo = (now - dismissed) / (1000 * 60 * 60 * 24);
    return daysAgo > RE_SHOW_AFTER_DAYS;
  } catch {
    return true;
  }
}

function dismiss() {
  try {
    localStorage.setItem(STORAGE_KEY, new Date().toISOString());
  } catch {
    /* noop */
  }
}

export function V2MigrationBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // Defer 2s so non disturba il first paint
    const t = window.setTimeout(() => setVisible(shouldShow()), 2000);
    return () => window.clearTimeout(t);
  }, []);

  if (!visible) return null;

  return (
    <div
      role="banner"
      className="px-3 py-2 bg-emerald-500/10 border-b border-emerald-500/30 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-sm"
    >
      <span className="flex-1">
        ✨ <strong>Prova la nuova CARA</strong> — sfondo bianco, voce
        più fluida, più veloce. Funziona accanto a questa.
      </span>
      <div className="flex gap-2 flex-shrink-0">
        <a
          href={V2_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="px-3 py-1 rounded bg-emerald-500 text-white text-xs font-medium hover:bg-emerald-600 transition-colors"
        >
          Apri v2
        </a>
        <button
          onClick={() => {
            dismiss();
            setVisible(false);
          }}
          className="px-3 py-1 text-xs text-text-secondary hover:text-text-primary"
        >
          Più tardi
        </button>
      </div>
    </div>
  );
}
