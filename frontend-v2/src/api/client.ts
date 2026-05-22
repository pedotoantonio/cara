// API client base — fetch wrapper con bearer + refresh + retry.
// Backend v1 espone /api/v1 same-origin (dietro nginx-proxy in prod, via
// proxy Vite in dev). JWT in localStorage via authStorage 3-tier.

import { getItem, removeItem, setItem } from '@/lib/authStorage';

const API_BASE = '/api/v1';
const TOKEN_KEY = 'cara.access_token';
const REFRESH_KEY = 'cara.refresh_token';

export class ApiError extends Error {
  constructor(public status: number, public detail: string, public payload?: unknown) {
    super(detail);
    this.name = 'ApiError';
  }
}

/**
 * Errore di rete/CORS/cert/DNS — il request NON ha prodotto risposta HTTP.
 * NON cancellare token in questo caso: l'utente è autenticato, è una blip.
 */
export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NetworkError';
  }
}

export function getAccessToken(): string | null {
  return getItem(TOKEN_KEY);
}

export function setTokens(access: string, refresh: string) {
  setItem(TOKEN_KEY, access);
  setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  removeItem(TOKEN_KEY);
  removeItem(REFRESH_KEY);
}

async function rawFetch(input: string, init: RequestInit, token?: string | null): Promise<Response> {
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !headers.has('Content-Type') && typeof init.body === 'string') {
    headers.set('Content-Type', 'application/json');
  }
  try {
    return await fetch(input, { ...init, headers });
  } catch (err) {
    throw new NetworkError((err as Error).message || 'network error');
  }
}

async function refreshOnce(): Promise<string | null> {
  const refresh = getItem(REFRESH_KEY);
  if (!refresh) return null;
  try {
    const r = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!r.ok) return null;
    const data = (await r.json()) as { access_token: string; refresh_token: string };
    setTokens(data.access_token, data.refresh_token);
    return data.access_token;
  } catch {
    return null;
  }
}

/**
 * authFetch — fetch con auto-refresh su 401. Throws ApiError per 4xx/5xx con detail,
 * NetworkError per failures sotto HTTP layer.
 */
export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  let token = getAccessToken();
  let resp = await rawFetch(url, init, token);
  if (resp.status === 401 && token) {
    const fresh = await refreshOnce();
    if (fresh) {
      token = fresh;
      resp = await rawFetch(url, init, token);
    } else {
      clearTokens();
    }
  }
  return resp;
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await authFetch(path);
  if (!r.ok) {
    const detail = await r
      .json()
      .then((j) => j.detail ?? `HTTP ${r.status}`)
      .catch(() => `HTTP ${r.status}`);
    throw new ApiError(r.status, String(detail));
  }
  return r.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const r = await authFetch(path, {
    method: 'POST',
    body: body == null ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r
      .json()
      .then((j) => j.detail ?? `HTTP ${r.status}`)
      .catch(() => `HTTP ${r.status}`);
    throw new ApiError(r.status, String(detail));
  }
  return r.json() as Promise<T>;
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const r = await authFetch(path, { method: 'PATCH', body: JSON.stringify(body) });
  if (!r.ok) {
    const detail = await r
      .json()
      .then((j) => j.detail ?? `HTTP ${r.status}`)
      .catch(() => `HTTP ${r.status}`);
    throw new ApiError(r.status, String(detail));
  }
  return r.json() as Promise<T>;
}

export async function apiDelete(path: string): Promise<void> {
  const r = await authFetch(path, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) {
    throw new ApiError(r.status, `delete failed: ${r.status}`);
  }
}

export { API_BASE };
