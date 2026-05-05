import { useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { clearTokens, fetchMe, getToken } from './api/auth';
import type { User } from './api/auth';
import { getVoiceConfig } from './api/voice';
import { AmbientStateBanner } from './components/AmbientStateBanner';
import { AppShell } from './components/AppShell';
import { DebugOverlay } from './components/DebugOverlay';
import { InstallPwaPrompt } from './components/InstallPwaPrompt';
import { Login } from './components/Login';
import { ThemeProvider, ToastProvider } from './design';
import { CdaPlayerProvider } from './lib/cdaPlayer';
import { RadioPlayerProvider } from './lib/radioPlayer';
import { ReactionsProvider, useReactions } from './lib/reactions';
import { setSoundsEnabled, setVolume } from './lib/sounds';
import { setVoiceConfig } from './lib/speech';
import { loadPrefs } from './lib/userPrefs';

// Apply persisted sound prefs on first import.
const _initialPrefs = loadPrefs();
setSoundsEnabled(_initialPrefs.soundsEnabled);
setVolume(_initialPrefs.soundsVolume);

const BIRTHDAY_FLAG_KEY = 'cara.birthday-greeted';

/**
 * Trigger a `birthday` reaction once per day if today's month/day matches the
 * current user's birth_date. Persisted via localStorage so a refresh on the
 * same day does not re-trigger.
 */
function BirthdayWatcher({ user }: { user: User }) {
  const reactions = useReactions();
  useEffect(() => {
    if (!user.birth_date) return;
    const today = new Date();
    const todayKey = `${today.getFullYear()}-${today.getMonth() + 1}-${today.getDate()}`;
    const flagKey = `${BIRTHDAY_FLAG_KEY}.${user.id}.${todayKey}`;
    if (localStorage.getItem(flagKey)) return;
    const bd = new Date(user.birth_date);
    if (bd.getMonth() === today.getMonth() && bd.getDate() === today.getDate()) {
      const name = user.full_name?.split(' ')[0] ?? 'tu';
      // Small delay so the rest of the UI mounts first.
      const t = setTimeout(() => {
        reactions.trigger('birthday', { message: `Buon compleanno ${name}! 🎂` });
        localStorage.setItem(flagKey, '1');
      }, 800);
      return () => clearTimeout(t);
    }
  }, [user, reactions]);
  return null;
}
import { AdminMemoryPage } from './routes/AdminMemoryPage';
import { AdminPage } from './routes/AdminPage';
import { AdminDevicesPage } from './routes/AdminDevicesPage';
import { AdminProactivityPage } from './routes/AdminProactivityPage';
import { AdminSkillsPage } from './routes/AdminSkillsPage';
import { AdminSmartHomePage } from './routes/AdminSmartHomePage';
import { PairPage } from './routes/PairPage';
import { ChatPage } from './routes/ChatPage';
import { DiagnosticsPage } from './routes/DiagnosticsPage';
import { DiscoveriesPage } from './routes/DiscoveriesPage';
import { FaceLabPage } from './routes/FaceLabPage';
import { HomePage } from './routes/HomePage';
import { IntegrationsPage } from './routes/IntegrationsPage';
import { MemoryPage } from './routes/MemoryPage';
import { NewsPage } from './routes/NewsPage';
import { NotesPage } from './routes/NotesPage';
import { ProposalsPage } from './routes/ProposalsPage';
import { RadioPage } from './routes/RadioPage';
import { SettingsPage } from './routes/SettingsPage';
import { ShoppingPage } from './routes/ShoppingPage';
import { TasksPage } from './routes/TasksPage';
import { WalletPage } from './routes/WalletPage';

type AuthState = { kind: 'loading' } | { kind: 'anonymous' } | { kind: 'authenticated'; user: User };

export default function App() {
  const [auth, setAuth] = useState<AuthState>({ kind: 'loading' });

  useEffect(() => {
    if (!getToken()) {
      setAuth({ kind: 'anonymous' });
      return;
    }
    fetchMe()
      .then((user) => setAuth({ kind: 'authenticated', user }))
      .catch(() => {
        clearTokens();
        setAuth({ kind: 'anonymous' });
      });
  }, []);

  // Pull admin-set voice knobs once the user is authenticated, so every
  // call to `speak()` uses the configured pitch/rate/volume/voice name.
  useEffect(() => {
    if (auth.kind !== 'authenticated') return;
    getVoiceConfig()
      .then((cfg) => setVoiceConfig(cfg))
      .catch(() => undefined);
    // Re-POST the existing browser push subscription so a backend that
    // lost its row (or a fresh device login) gets re-bound silently.
    void import('./lib/push').then(({ reaffirmSubscriptionSilently }) =>
      reaffirmSubscriptionSilently(),
    );
    // Start the WebSocket family sync. Cross-tab reconcile happens via
    // `onFamilyEvent` listeners in each route that owns mutable lists.
    void import('./lib/familySync').then(({ startFamilySync }) => startFamilySync());
    return () => {
      void import('./lib/familySync').then(({ stopFamilySync }) => stopFamilySync());
    };
  }, [auth.kind]);

  function refreshMe() {
    fetchMe()
      .then((user) => setAuth({ kind: 'authenticated', user }))
      .catch(() => {
        clearTokens();
        setAuth({ kind: 'anonymous' });
      });
  }

  function logout() {
    clearTokens();
    setAuth({ kind: 'anonymous' });
  }

  if (auth.kind === 'loading') {
    return (
      <ThemeProvider>
        <main className="min-h-dvh flex items-center justify-center bg-bg text-fg-muted text-sm">
          <span className="animate-breathe">cara sta arrivando…</span>
        </main>
      </ThemeProvider>
    );
  }

  if (auth.kind === 'anonymous') {
    // /pair is the device-pairing page that an unauthenticated wall /
    // mobile / TV opens to obtain its device token. It bypasses the
    // user login gate.
    if (typeof window !== 'undefined' && window.location.pathname.startsWith('/pair')) {
      return (
        <ThemeProvider>
          <ToastProvider>
            <PairPage />
          </ToastProvider>
        </ThemeProvider>
      );
    }
    return (
      <ThemeProvider>
        <ToastProvider>
          <Login onSuccess={refreshMe} />
        </ToastProvider>
      </ThemeProvider>
    );
  }

  return (
    <ThemeProvider>
    <ToastProvider>
    <BrowserRouter>
      <RadioPlayerProvider>
      <CdaPlayerProvider>
      <ReactionsProvider>
      <BirthdayWatcher user={auth.user} />
      <InstallPwaPrompt />
      <AmbientStateBanner />
      <DebugOverlay />
      <Routes>
        <Route
          path="/"
          element={<AppShell user={auth.user} onLogout={logout} refreshMe={refreshMe} />}
        >
          <Route index element={<HomePage />} />
          <Route path="home" element={<Navigate to="/" replace />} />
          <Route path="wallet" element={<WalletPage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="tasks" element={<TasksPage />} />
          <Route path="shopping" element={<ShoppingPage />} />
          <Route path="notes" element={<NotesPage />} />
          <Route path="news" element={<NewsPage />} />
          <Route path="radio" element={<RadioPage />} />
          <Route path="discoveries" element={<DiscoveriesPage />} />
          <Route path="admin" element={<AdminPage />} />
          <Route path="admin/diagnostics" element={<DiagnosticsPage />} />
          <Route path="admin/memory" element={<AdminMemoryPage />} />
          <Route path="admin/smart-home" element={<AdminSmartHomePage />} />
          <Route path="admin/proactivity" element={<AdminProactivityPage />} />
          <Route path="admin/skills" element={<AdminSkillsPage />} />
          <Route path="admin/devices" element={<AdminDevicesPage />} />
          <Route path="pair" element={<PairPage />} />
          <Route path="face-lab" element={<FaceLabPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="me/memory" element={<MemoryPage />} />
          <Route path="me/integrazioni" element={<IntegrationsPage />} />
          <Route path="me/proposte" element={<ProposalsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
      </ReactionsProvider>
      </CdaPlayerProvider>
      </RadioPlayerProvider>
    </BrowserRouter>
    </ToastProvider>
    </ThemeProvider>
  );
}
