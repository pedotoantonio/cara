// API client for the Reminders (Memorial) module.
//
// Surface: a flat list of CRUD helpers + the templates catalog. The
// router lives at /api/v1/reminders; auth via the shared authFetch
// (Bearer token / LAN auto-login behind the scenes).

import { authFetch } from './auth';

const API = '/api/v1';

export type ReminderCategory = 'family' | 'health' | 'documents' | 'events';

export interface TemplateField {
  key: string;
  label: string;
  type: 'text' | 'date' | 'datetime' | 'family_picker' | 'lead_time_picker' | 'select';
  required?: boolean;
  placeholder?: string;
  options?: { value: string; label: string }[];
}

export interface ReminderTemplate {
  id: string;
  slug: string;
  category: ReminderCategory;
  title_it: string;
  icon: string;
  fields: TemplateField[];
  default_lead_times: number[];
  default_recurrence: string | null;
  order_in_category: number;
}

export type ReminderStatus = 'active' | 'done' | 'snoozed' | 'archived';

export interface Reminder {
  id: string;
  user_id: number;
  family_id: number | null;
  template_slug: string | null;
  category: ReminderCategory;
  title: string;
  notes: string | null;
  due_at: string;
  recurrence: string | null;
  recurrence_until: string | null;
  lead_times: number[];
  channels: Record<string, unknown>;
  status: ReminderStatus;
  snooze_until: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReminderCreatePayload {
  template_slug?: string;
  category?: ReminderCategory;
  title?: string;
  notes?: string | null;
  family_id?: number | null;
  due_at: string;                  // ISO 8601
  recurrence?: string | null;
  recurrence_until?: string | null;
  lead_times?: number[];
  channels?: Record<string, unknown>;
  extras?: Record<string, unknown>;
}

export type ReminderUpdatePayload = Partial<{
  title: string;
  notes: string | null;
  due_at: string;
  family_id: number | null;
  recurrence: string | null;
  recurrence_until: string | null;
  lead_times: number[];
  channels: Record<string, unknown>;
  status: ReminderStatus;
}>;

// ── Templates ──────────────────────────────────────────────────

export async function listTemplates(
  category?: ReminderCategory,
): Promise<ReminderTemplate[]> {
  const q = category ? `?category=${category}` : '';
  const r = await authFetch(`${API}/reminders/templates${q}`);
  if (!r.ok) throw new Error(`templates: ${r.status}`);
  return r.json();
}

// ── Reminders ──────────────────────────────────────────────────

export async function listReminders(opts?: {
  upcomingDays?: number;
  category?: ReminderCategory;
  includeDone?: boolean;
}): Promise<Reminder[]> {
  const p = new URLSearchParams();
  if (opts?.upcomingDays !== undefined) p.set('upcoming_days', String(opts.upcomingDays));
  if (opts?.category) p.set('category', opts.category);
  if (opts?.includeDone) p.set('include_done', 'true');
  const r = await authFetch(`${API}/reminders?${p.toString()}`);
  if (!r.ok) throw new Error(`list: ${r.status}`);
  return r.json();
}

export async function listUpcoming(days = 7, limit = 20): Promise<Reminder[]> {
  const r = await authFetch(`${API}/reminders/upcoming?days=${days}&limit=${limit}`);
  if (!r.ok) throw new Error(`upcoming: ${r.status}`);
  return r.json();
}

export async function createReminder(payload: ReminderCreatePayload): Promise<Reminder> {
  const r = await authFetch(`${API}/reminders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const txt = await r.text().catch(() => '');
    throw new Error(`create: ${r.status} ${txt}`);
  }
  return r.json();
}

export async function updateReminder(
  id: string,
  payload: ReminderUpdatePayload,
): Promise<Reminder> {
  const r = await authFetch(`${API}/reminders/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`update: ${r.status}`);
  return r.json();
}

export async function markDone(id: string): Promise<Reminder> {
  const r = await authFetch(`${API}/reminders/${id}/done`, { method: 'POST' });
  if (!r.ok) throw new Error(`done: ${r.status}`);
  return r.json();
}

export async function snooze(
  id: string,
  opts: { durationMinutes?: number; until?: string },
): Promise<Reminder> {
  const body: Record<string, unknown> = {};
  if (opts.durationMinutes !== undefined) body.duration_minutes = opts.durationMinutes;
  if (opts.until !== undefined) body.until = opts.until;
  const r = await authFetch(`${API}/reminders/${id}/snooze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`snooze: ${r.status}`);
  return r.json();
}

export async function deleteReminder(id: string): Promise<void> {
  const r = await authFetch(`${API}/reminders/${id}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`delete: ${r.status}`);
}

// ── Helpers ────────────────────────────────────────────────────

export const CATEGORY_META: Record<
  ReminderCategory,
  { label: string; emoji: string; tint: 'rose' | 'mint' | 'amber' | 'plum'; description: string }
> = {
  family:    { label: 'Famiglia',  emoji: '👨‍👩‍👧', tint: 'rose',  description: 'Compleanni, eventi scuola, anniversari' },
  health:    { label: 'Salute',    emoji: '🩺',   tint: 'mint',  description: 'Visite, esami, terapie, controlli' },
  documents: { label: 'Documenti', emoji: '📄',   tint: 'amber', description: 'Carta d\'identità, patente, scadenze' },
  events:    { label: 'Eventi',    emoji: '🎉',   tint: 'plum',  description: 'Concerti, viaggi, prenotazioni' },
};

/** Human-ish "fra X" for a lead-time integer in minutes. */
export function leadTimeLabel(m: number): string {
  if (m % (60 * 24 * 7) === 0) {
    const w = m / (60 * 24 * 7);
    return w === 1 ? '1 settimana prima' : `${w} settimane prima`;
  }
  if (m % (60 * 24) === 0) {
    const d = m / (60 * 24);
    return d === 1 ? '1 giorno prima' : `${d} giorni prima`;
  }
  if (m % 60 === 0) {
    const h = m / 60;
    return h === 1 ? '1 ora prima' : `${h} ore prima`;
  }
  return `${m} min prima`;
}

/** Format the due date for human reading. Italian, "oggi", "domani", etc. */
export function formatDue(iso: string): { primary: string; secondary: string; tone: 'alert' | 'today' | 'soon' | 'far' } {
  const dt = new Date(iso);
  const now = new Date();
  const diffMs = dt.getTime() - now.getTime();
  const diffDays = Math.floor(diffMs / 86_400_000);

  const sameDay =
    dt.getFullYear() === now.getFullYear() &&
    dt.getMonth() === now.getMonth() &&
    dt.getDate() === now.getDate();

  const time = dt.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
  const date = dt.toLocaleDateString('it-IT', { day: '2-digit', month: 'long', year: dt.getFullYear() === now.getFullYear() ? undefined : 'numeric' });

  if (diffMs < 0)    return { primary: 'in ritardo', secondary: `${date} · ${time}`, tone: 'alert' };
  if (sameDay)       return { primary: `oggi · ${time}`, secondary: date, tone: 'today' };
  if (diffDays < 1)  return { primary: `domani · ${time}`, secondary: date, tone: 'today' };
  if (diffDays < 7)  return { primary: `tra ${diffDays + 1} giorni`, secondary: `${date} · ${time}`, tone: 'soon' };
  return { primary: date, secondary: time, tone: 'far' };
}
