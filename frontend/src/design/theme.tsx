// Theme provider — day / night / auto.
// "auto" segue il sole locale: 06:00→20:30 day, altrimenti night.
// L'utente può forzare; la scelta viene salvata in localStorage.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

export type ThemeMode = 'day' | 'night' | 'auto';
export type ResolvedTheme = 'day' | 'night';

interface ThemeCtx {
  mode: ThemeMode;
  resolved: ResolvedTheme;
  setMode: (m: ThemeMode) => void;
  toggle: () => void;
}

const Ctx = createContext<ThemeCtx | null>(null);
const STORAGE_KEY = 'cara.theme.mode';

function resolveAuto(now = new Date()): ResolvedTheme {
  // Mattina chiara, sera profonda. Wrappa anche oltre mezzanotte.
  const h = now.getHours();
  const m = now.getMinutes();
  const minutes = h * 60 + m;
  const sunrise = 6 * 60;        // 06:00
  const sunset  = 20 * 60 + 30;  // 20:30
  return minutes >= sunrise && minutes < sunset ? 'day' : 'night';
}

function readStoredMode(): ThemeMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'day' || v === 'night' || v === 'auto') return v;
  } catch {/* SSR / privacy mode */}
  return 'auto';
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => readStoredMode());
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    mode === 'auto' ? resolveAuto() : mode,
  );

  // Recompute on mode change.
  useEffect(() => {
    setResolved(mode === 'auto' ? resolveAuto() : mode);
  }, [mode]);

  // Auto: re-evaluate every 5 min so we transition at sunset/sunrise.
  useEffect(() => {
    if (mode !== 'auto') return;
    const id = window.setInterval(() => setResolved(resolveAuto()), 5 * 60 * 1000);
    return () => window.clearInterval(id);
  }, [mode]);

  // Apply data-theme on <html> for CSS variables (see tailwind plugin).
  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
    document.documentElement.style.colorScheme = resolved === 'night' ? 'dark' : 'light';
  }, [resolved]);

  const setMode = useCallback((m: ThemeMode) => {
    setModeState(m);
    try { localStorage.setItem(STORAGE_KEY, m); } catch {/* ignore */}
  }, []);

  const toggle = useCallback(() => {
    setMode(resolved === 'day' ? 'night' : 'day');
  }, [resolved, setMode]);

  const value = useMemo(() => ({ mode, resolved, setMode, toggle }),
                         [mode, resolved, setMode, toggle]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useTheme outside ThemeProvider');
  return v;
}
