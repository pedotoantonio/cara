// API client per i dati della Hub Casa.
import { apiGet, authFetch } from './client';

export interface TaskItem {
  id: string;
  title: string;
  due_date: string | null;
  done: boolean;
  user_id: number;
}

export interface ReminderUpcoming {
  id: number;
  title: string;
  due_at: string;
  category: string;
  status: string;
}

export interface WeatherCurrent {
  temperature: number | null;
  apparent: number | null;
  icon_slug: string;
  label: string;
  city: string;
}

export async function listTasks(): Promise<TaskItem[]> {
  return apiGet<TaskItem[]>('/tasks');
}

export async function listRemindersUpcoming(days = 7): Promise<ReminderUpcoming[]> {
  try {
    return await apiGet<ReminderUpcoming[]>(`/reminders/upcoming?days=${days}&limit=10`);
  } catch {
    return [];
  }
}

export async function fetchWeather(lat: number, lon: number): Promise<WeatherCurrent | null> {
  try {
    return await apiGet<WeatherCurrent>(`/weather/current?lat=${lat}&lon=${lon}`);
  } catch {
    return null;
  }
}

export async function fetchFamilyResidence(): Promise<{ lat: number; lon: number; city: string } | null> {
  // Letto dall'admin_settings via endpoint pubblico /weather (che riusa
  // family_lat/family_lon dall'admin). In assenza, fallback Ferrara.
  try {
    const r = await authFetch('/admin/settings');
    if (!r.ok) throw new Error('admin only');
    const data = (await r.json()) as Record<string, unknown>;
    return {
      lat: Number(data.family_lat ?? 44.83804),
      lon: Number(data.family_lon ?? 11.62057),
      city: String(data.family_city ?? 'Ferrara'),
    };
  } catch {
    return { lat: 44.83804, lon: 11.62057, city: 'Ferrara' };
  }
}
