import { useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { clearTokens, fetchMe, getToken } from './api/auth';
import type { User } from './api/auth';
import { getVoiceConfig } from './api/voice';
import { AppShell } from './components/AppShell';
import { Login } from './components/Login';
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
import { AdminPage } from './routes/AdminPage';
import { ChatPage } from './routes/ChatPage';
import { FaceLabPage } from './routes/FaceLabPage';
import { HomePage } from './routes/HomePage';
import { NewsPage } from './routes/NewsPage';
import { NotesPage } from './routes/NotesPage';
import { RadioPage } from './routes/RadioPage';
import { SettingsPage } from './routes/SettingsPage';
import { ShoppingPage } from './routes/ShoppingPage';
import { TasksPage } from './routes/TasksPage';

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
      <main className="min-h-dvh flex items-center justify-center bg-slate-900 text-slate-500 text-sm">
        connecting…
      </main>
    );
  }

  if (auth.kind === 'anonymous') {
    return <Login onSuccess={refreshMe} />;
  }

  return (
    <BrowserRouter>
      <RadioPlayerProvider>
      <ReactionsProvider>
      <BirthdayWatcher user={auth.user} />
      <Routes>
        <Route
          path="/"
          element={<AppShell user={auth.user} onLogout={logout} refreshMe={refreshMe} />}
        >
          <Route index element={<HomePage />} />
          <Route path="home" element={<Navigate to="/" replace />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="tasks" element={<TasksPage />} />
          <Route path="shopping" element={<ShoppingPage />} />
          <Route path="notes" element={<NotesPage />} />
          <Route path="news" element={<NewsPage />} />
          <Route path="radio" element={<RadioPage />} />
          <Route path="admin" element={<AdminPage />} />
          <Route path="face-lab" element={<FaceLabPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
      </ReactionsProvider>
      </RadioPlayerProvider>
    </BrowserRouter>
  );
}
