// Auth store — Zustand
import { create } from 'zustand';
import type { User } from '@/api/auth';
import { fetchMe, login as apiLogin, logout as apiLogout, tryLanLogin } from '@/api/auth';
import { getAccessToken, NetworkError } from '@/api/client';

type AuthStatus = 'idle' | 'loading' | 'authenticated' | 'unauthenticated' | 'network_error';

interface AuthState {
  status: AuthStatus;
  user: User | null;
  error: string | null;
  bootstrap: () => Promise<void>;
  loginWithCredentials: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshMe: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: 'idle',
  user: null,
  error: null,

  bootstrap: async () => {
    set({ status: 'loading', error: null });

    // 1) If we have a token, try to use it.
    if (getAccessToken()) {
      try {
        const user = await fetchMe();
        set({ status: 'authenticated', user });
        return;
      } catch (err) {
        if (err instanceof NetworkError) {
          // Cert / DNS / 5xx — DON'T clear tokens, the user is probably
          // still authenticated and the network is just having a moment.
          set({ status: 'network_error', error: 'Connessione assente o instabile.' });
          return;
        }
        // 401 → clear, continue to LAN-login attempt below.
      }
    }

    // 2) No token, or token rejected — try LAN auto-login.
    const lanOk = await tryLanLogin();
    if (lanOk) {
      try {
        const user = await fetchMe();
        set({ status: 'authenticated', user });
        return;
      } catch {
        /* fall through */
      }
    }

    set({ status: 'unauthenticated', user: null });
  },

  loginWithCredentials: async (email, password) => {
    set({ status: 'loading', error: null });
    try {
      await apiLogin(email, password);
      const user = await fetchMe();
      set({ status: 'authenticated', user });
    } catch (err) {
      set({ status: 'unauthenticated', error: (err as Error).message });
      throw err;
    }
  },

  logout: () => {
    apiLogout();
    set({ status: 'unauthenticated', user: null, error: null });
  },

  refreshMe: async () => {
    try {
      const user = await fetchMe();
      set({ user });
    } catch {
      /* swallow — bootstrap will catch real auth issues */
    }
  },
}));
