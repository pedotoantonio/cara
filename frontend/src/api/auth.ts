import { getItem, setItem, removeItem } from '../lib/authStorage';

const API = '/api/v1';
const TOKEN_KEY = 'cara.access_token';
const REFRESH_KEY = 'cara.refresh_token';

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  is_admin: boolean;
  is_active: boolean;
  role?: string;
  birth_date?: string | null;
  created_at: string;
}

export function getToken(): string | null {
  return getItem(TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  return getItem(REFRESH_KEY);
}

export function setTokens(access: string, refresh: string) {
  setItem(TOKEN_KEY, access);
  setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  removeItem(TOKEN_KEY);
  removeItem(REFRESH_KEY);
}

/**
 * Custom error raised by `fetchMe` when the network/CORS/cert layer
 * fails BEFORE we get a real HTTP response. The App layer should NOT
 * clear tokens in this case — the user is probably still logged in,
 * the connection is just blip.
 */
export class AuthNetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AuthNetworkError';
  }
}

export async function login(email: string, password: string): Promise<void> {
  const r = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) {
    const detail = await r
      .json()
      .then((j) => j.detail ?? `HTTP ${r.status}`)
      .catch(() => `HTTP ${r.status}`);
    throw new Error(detail);
  }
  const data = (await r.json()) as { access_token: string; refresh_token: string };
  setTokens(data.access_token, data.refresh_token);
  // Verify the write actually persisted (private mode / Safari ITP /
  // standalone PWA can silently no-op). Without this check the user
  // would think login succeeded, then loop back to the login screen
  // on every page load.
  if (getToken() !== data.access_token) {
    throw new Error(
      'Storage del browser non disponibile. Disattiva la modalità in incognito o '
      + 'concedi a CARA il permesso di salvare i dati del sito.',
    );
  }
}

export async function fetchMe(): Promise<User> {
  let r: Response;
  try {
    r = await authFetch(`${API}/auth/me`);
  } catch (err) {
    // Network / CORS / cert / DNS — the request never produced an
    // HTTP response. We must NOT clear tokens for this: the user is
    // likely still authenticated, just temporarily disconnected.
    throw new AuthNetworkError((err as Error).message || 'network error');
  }
  if (r.status === 401) {
    // True auth failure — caller should clear tokens.
    throw new Error(`HTTP 401`);
  }
  if (!r.ok) {
    // 5xx etc. — backend issue, not auth. Treat as network so we
    // don't kick the user out on a transient server error.
    throw new AuthNetworkError(`HTTP ${r.status}`);
  }
  return r.json();
}

export async function updateMe(changes: {
  full_name?: string | null;
  birth_date?: string | null;
}): Promise<User> {
  const r = await authFetch(`${API}/auth/me`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  });
  if (!r.ok) {
    const detail = await r.json().then((j) => j.detail).catch(() => `HTTP ${r.status}`);
    throw new Error(detail);
  }
  return r.json();
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const r = await authFetch(`${API}/auth/change-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!r.ok) {
    const detail = await r.json().then((j) => j.detail).catch(() => `HTTP ${r.status}`);
    throw new Error(detail);
  }
}

/**
 * `fetch` wrapper that injects the Bearer token. On 401 it tries one refresh;
 * if refresh fails it clears tokens and throws so the caller can redirect to login.
 */
export async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  let resp = await fetch(input, { ...init, headers });
  if (resp.status !== 401) return resp;

  // Try refresh once
  const refresh = getRefreshToken();
  if (!refresh) {
    clearTokens();
    return resp;
  }
  const r = await fetch(`${API}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!r.ok) {
    clearTokens();
    return resp;
  }
  const data = (await r.json()) as { access_token: string; refresh_token: string };
  setTokens(data.access_token, data.refresh_token);

  // Retry original request with the new token
  const headers2 = new Headers(init.headers);
  headers2.set('Authorization', `Bearer ${data.access_token}`);
  resp = await fetch(input, { ...init, headers: headers2 });
  return resp;
}

/** Helper for fetch-based callers that need to know the bearer at call time. */
export function authHeaders(): HeadersInit {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}
