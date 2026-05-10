// Wall API client. Public endpoints — uses plain fetch (no Bearer
// header). The backend gates access via LAN CIDR check, not JWT.

const API = '/api/v1/wall';

export interface WallUser {
  id: number;
  display_name: string;
  role: string;
  color: string;
  emoji: string;
  wall_visible: boolean;
}

export interface WallItem {
  id: string | number;
  title: string;
  // tasks → due_date; events → start
  due_date?: string | null;
  start?: string | null;
  end?: string | null;
  done?: boolean;
  all_day?: boolean;
  owner_id: number | null;
  owner: WallUser | null;
  kind: 'task' | 'event';
}

export interface WallSummary {
  now: string;
  today: { items: WallItem[]; open_no_date: WallItem[] };
  upcoming: { date: string; count: number; preview: WallItem[] }[];
  family: WallUser[];
  pending_by_owner: { owner: WallUser; count: number; overdue: number }[];
  presence: {
    available: boolean;
    people: { name: string; minutes_ago: number }[];
  };
  weather: {
    available: boolean;
    city?: string | null;
    label?: string;
    icon_slug?: string;
    temperature_c?: number;
    apparent_c?: number | null;
    is_day?: boolean;
  };
}

export interface WallDay {
  date: string;
  in_month?: boolean;
  is_today: boolean;
  is_weekend: boolean;
  is_holiday: boolean;
  items: WallItem[];
}

export interface WallCalendar {
  year: number;
  month: number;
  grid_start: string;
  grid_end: string;
  days: WallDay[];
  family: WallUser[];
}

export interface WallWeek {
  start: string;
  end: string;
  days: WallDay[];
  family: WallUser[];
}

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { credentials: 'omit' });
  if (!r.ok) {
    throw new Error(`Wall ${path} → HTTP ${r.status}`);
  }
  return (await r.json()) as T;
}

export function fetchSummary(): Promise<WallSummary> {
  return getJson<WallSummary>('/summary');
}

export function fetchCalendar(year: number, month: number): Promise<WallCalendar> {
  return getJson<WallCalendar>(`/calendar?year=${year}&month=${month}`);
}

export function fetchWeek(startISO: string): Promise<WallWeek> {
  return getJson<WallWeek>(`/week?start=${startISO}`);
}

export function fetchFamily(): Promise<WallUser[]> {
  return getJson<WallUser[]>('/family');
}

export const WALL_EVENTS_URL = `${API}/events/stream`;

// ─── Voice ask ────────────────────────────────────────────────────

export interface WallAskOut {
  text: string;
  audio_base64: string | null;
  audio_mime: string | null;
  sample_rate: number | null;
}

export async function askCara(text: string, voice = true): Promise<WallAskOut> {
  const r = await fetch(`${API}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'omit',
    body: JSON.stringify({ text, voice }),
  });
  if (!r.ok) {
    throw new Error(`Wall /ask → HTTP ${r.status}`);
  }
  return (await r.json()) as WallAskOut;
}

// ─── Cameras ──────────────────────────────────────────────────────

export interface WallCamera {
  id: string;
  label: string;
  area: string | null;
  online: boolean;
  last_seen: string | null;
  snapshot_url: string;
}

export function fetchCameras(): Promise<WallCamera[]> {
  return getJson<WallCamera[]>('/cameras');
}

export function snapshotUrl(camId: string, bust: number): string {
  return `${API}/cameras/${encodeURIComponent(camId)}/snapshot.jpg?t=${bust}`;
}

// ─── ASR fallback (Whisper) ──────────────────────────────────────

export async function transcribeAudio(blob: Blob, language = 'it'): Promise<string> {
  const fd = new FormData();
  fd.append('audio', blob, 'recording.webm');
  fd.append('language', language);
  const r = await fetch(`${API}/asr`, {
    method: 'POST',
    body: fd,
    credentials: 'omit',
  });
  if (!r.ok) {
    throw new Error(`Wall /asr → HTTP ${r.status}`);
  }
  const data = await r.json();
  return (data.text || '').trim();
}

// ─── Tasks edit ──────────────────────────────────────────────────

export interface WallTaskFull {
  id: string;
  title: string;
  due_date: string | null;
  done: boolean;
  owner_id: number;
  owner: WallUser | null;
  wall_visible: boolean;
  kind: 'task';
}

export async function getTask(id: string): Promise<WallTaskFull> {
  return getJson<WallTaskFull>(`/tasks/${id}`);
}

export async function patchTask(
  id: string,
  patch: Partial<{
    title: string;
    due_date: string | null;
    done: boolean;
    owner_id: number;
    wall_visible: boolean;
  }>,
): Promise<WallTaskFull> {
  const r = await fetch(`${API}/tasks/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'omit',
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(`Wall PATCH /tasks → HTTP ${r.status}`);
  return (await r.json()) as WallTaskFull;
}

export async function createTask(payload: {
  title: string;
  due_date?: string | null;
  owner_id?: number;
}): Promise<WallTaskFull> {
  const r = await fetch(`${API}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'omit',
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`Wall POST /tasks → HTTP ${r.status}`);
  return (await r.json()) as WallTaskFull;
}

export async function deleteTask(id: string): Promise<void> {
  const r = await fetch(`${API}/tasks/${id}`, {
    method: 'DELETE',
    credentials: 'omit',
  });
  if (!r.ok && r.status !== 204) {
    throw new Error(`Wall DELETE /tasks → HTTP ${r.status}`);
  }
}

// ─── Shopping ────────────────────────────────────────────────────

export interface WallShoppingItem {
  id: string;
  title: string;
  qty: string | null;
  bought: boolean;
  owner_id: number;
  owner: WallUser | null;
  category: string;
  created_at: string | null;
}

export interface WallShopping {
  groups: { name: string; items: WallShoppingItem[] }[];
  bought: WallShoppingItem[];
  family: WallUser[];
  totals: { todo: number; bought: number };
}

export function fetchShopping(): Promise<WallShopping> {
  return getJson<WallShopping>('/shopping');
}

export async function createShopping(payload: {
  title: string;
  qty?: string | null;
  owner_id?: number;
}): Promise<WallShoppingItem> {
  const r = await fetch(`${API}/shopping`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'omit',
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`Wall POST /shopping → HTTP ${r.status}`);
  return (await r.json()) as WallShoppingItem;
}

export async function patchShopping(
  id: string,
  patch: Partial<{
    title: string;
    qty: string | null;
    bought: boolean;
    owner_id: number;
  }>,
): Promise<WallShoppingItem> {
  const r = await fetch(`${API}/shopping/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'omit',
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(`Wall PATCH /shopping → HTTP ${r.status}`);
  return (await r.json()) as WallShoppingItem;
}

export async function deleteShopping(id: string): Promise<void> {
  const r = await fetch(`${API}/shopping/${id}`, {
    method: 'DELETE',
    credentials: 'omit',
  });
  if (!r.ok && r.status !== 204) {
    throw new Error(`Wall DELETE /shopping → HTTP ${r.status}`);
  }
}

// ─── Device camera face recognition ──────────────────────────────

export interface WallFaceCheckResult {
  found_face: boolean;
  match: { name: string; person_id: number; distance: number } | null;
  cooldown_sec: number;
}

// ─── Service board ─────────────────────────────────────────────────

export type WallServiceColor = 'green' | 'yellow' | 'red' | 'gray';

export interface WallService {
  name: string;
  label: string;
  category: string;
  role: 'stateless' | 'stateful';
  exists: boolean;
  color: WallServiceColor;
  status: string;
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  restart_count: number;
  image: string | null;
}

export interface WallServicesSnapshot {
  items: WallService[];
  summary: { green: number; yellow: number; red: number; gray: number };
}

export function fetchServices(): Promise<WallServicesSnapshot> {
  return getJson<WallServicesSnapshot>('/services');
}

// ─── Health probes ────────────────────────────────────────────────

export type HealthStatus = 'ok' | 'warn' | 'fail' | 'unknown';

export interface HealthProbe {
  name: string;
  label: string;
  status: HealthStatus;
  last_check_at: string | null;
  last_ok_at: string | null;
  fail_streak: number;
  duration_ms: number | null;
  error: string;
}

export interface HealthSnapshot {
  items: HealthProbe[];
  summary: { ok: number; warn: number; fail: number; unknown: number };
}

export function fetchHealth(): Promise<HealthSnapshot> {
  return getJson<HealthSnapshot>('/services/health');
}

export async function runHealthNow(): Promise<HealthSnapshot> {
  const r = await fetch(`${API}/services/health/run`, {
    method: 'POST',
    credentials: 'omit',
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.json();
}

export interface WallWatchdogStatus {
  enabled: boolean;
  min_bad_ticks: number;
  escalate_bad_ticks: number;
}

export function fetchWatchdog(): Promise<WallWatchdogStatus> {
  return getJson<WallWatchdogStatus>('/services/watchdog');
}

export async function setWatchdog(enabled: boolean): Promise<{ enabled: boolean }> {
  const r = await fetch(`${API}/services/watchdog`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'omit',
    body: JSON.stringify({ enabled }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.json();
}

export async function serviceAction(
  name: string,
  action: 'start' | 'stop' | 'restart',
): Promise<{ name: string; action: string; ok: boolean; color: WallServiceColor; status: string }> {
  const r = await fetch(`${API}/services/${encodeURIComponent(name)}/${action}`, {
    method: 'POST',
    credentials: 'omit',
  });
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try {
      const j = await r.json();
      detail = j.detail ?? detail;
    } catch {/* ignore */}
    throw new Error(detail);
  }
  return await r.json();
}

export async function checkFaceFromDevice(blob: Blob): Promise<WallFaceCheckResult> {
  const fd = new FormData();
  fd.append('image', blob, 'frame.jpg');
  const r = await fetch(`${API}/face-check`, {
    method: 'POST',
    body: fd,
    credentials: 'omit',
  });
  if (!r.ok) {
    throw new Error(`Wall /face-check → HTTP ${r.status}`);
  }
  return (await r.json()) as WallFaceCheckResult;
}

export async function clearBoughtShopping(): Promise<void> {
  const r = await fetch(`${API}/shopping/clear-bought`, {
    method: 'POST',
    credentials: 'omit',
  });
  if (!r.ok && r.status !== 204) {
    throw new Error(`Wall clear-bought → HTTP ${r.status}`);
  }
}
