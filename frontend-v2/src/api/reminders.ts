import { apiGet, apiPost } from './client';

export interface Reminder {
  id: number;
  user_id: number;
  family_id?: number | null;
  template_slug: string | null;
  category: string;
  title: string;
  notes: string | null;
  due_at: string;
  status: string;
  snooze_until: string | null;
  completed_at: string | null;
  created_at: string;
}

export async function listUpcomingReminders(days = 14, limit = 50): Promise<Reminder[]> {
  return apiGet<Reminder[]>(`/reminders/upcoming?days=${days}&limit=${limit}`);
}

export async function listAllReminders(): Promise<Reminder[]> {
  try {
    return await apiGet<Reminder[]>('/reminders');
  } catch {
    return listUpcomingReminders(365, 200);
  }
}

export async function markReminderDone(id: number): Promise<void> {
  await apiPost(`/reminders/${id}/done`).catch(() => undefined);
}

export async function snoozeReminder(id: number, hours = 1): Promise<void> {
  await apiPost(`/reminders/${id}/snooze`, { hours }).catch(() => undefined);
}
