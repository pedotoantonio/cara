import { apiGet } from './client';
import type { Task } from './tasks';
import type { Reminder } from './reminders';

export interface CalendarEvent {
  id: string;
  summary: string;
  start: string;
  end: string | null;
  all_day?: boolean;
  source: 'google' | 'local';
  user_id?: number | null;
}

export async function listEvents(start: string, end: string): Promise<CalendarEvent[]> {
  try {
    return await apiGet<CalendarEvent[]>(
      `/events?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
    );
  } catch {
    return [];
  }
}

export interface UnifiedCalendarItem {
  id: string;
  kind: 'task' | 'reminder' | 'event';
  title: string;
  when: string;
  endWhen?: string | null;
  category?: string;
}

export function mergeForCalendar(
  events: CalendarEvent[],
  tasks: Task[],
  reminders: Reminder[],
): UnifiedCalendarItem[] {
  const out: UnifiedCalendarItem[] = [];
  for (const e of events) {
    out.push({
      id: `e-${e.id}`,
      kind: 'event',
      title: e.summary,
      when: e.start,
      endWhen: e.end,
    });
  }
  for (const t of tasks) {
    if (!t.due_date) continue;
    out.push({ id: `t-${t.id}`, kind: 'task', title: t.title, when: t.due_date });
  }
  for (const r of reminders) {
    out.push({
      id: `r-${r.id}`,
      kind: 'reminder',
      title: r.title,
      when: r.due_at,
      category: r.category,
    });
  }
  return out.sort((a, b) => +new Date(a.when) - +new Date(b.when));
}
