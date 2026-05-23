// API client per /api/v1/calendar/* — info giornaliere italiane.

import { authFetch } from './client';

export interface DayInfo {
  iso: string;
  day_name_it: string;
  month_name_it: string;
  long_format_it: string;
  week_number: number;
  is_weekend: boolean;
  is_holiday: boolean;
  holiday_name: string | null;
  season: 'inverno' | 'primavera' | 'estate' | 'autunno';
  saint: string | null;
  moon_phase: string;
  moon_phase_emoji: string;
  moon_illumination: number;
  sunrise: string | null;
  sunset: string | null;
  daylight_hours: number | null;
  proverb: string;
  countdowns: Array<{
    label: string;
    emoji: string;
    date: string;
    days_to: number;
  }>;
  notes: string[];
}

export interface Holiday {
  date: string;
  label: string;
  fixed: boolean;
}

export interface MonthSummary {
  year: number;
  month: number;
  month_name_it: string;
  days_total: number;
  holidays: Holiday[];
  week_count: number;
  moon_events: Array<{ date: string; phase: string; emoji: string }>;
}

export async function getDayInfo(dateIso?: string): Promise<DayInfo> {
  const url = dateIso
    ? `/calendar/day-info?date_iso=${dateIso}`
    : '/calendar/day-info';
  const r = await authFetch(url);
  if (!r.ok) throw new Error(`getDayInfo: ${r.status}`);
  return r.json();
}

export async function getYearHolidays(year?: number): Promise<Holiday[]> {
  const r = await authFetch(`/calendar/year-holidays${year ? `?year=${year}` : ''}`);
  if (!r.ok) throw new Error(`getYearHolidays: ${r.status}`);
  return r.json();
}

export async function getMonthInfo(
  year?: number,
  month?: number,
): Promise<MonthSummary> {
  const params = new URLSearchParams();
  if (year) params.set('year', String(year));
  if (month) params.set('month', String(month));
  const r = await authFetch(`/calendar/month-info?${params}`);
  if (!r.ok) throw new Error(`getMonthInfo: ${r.status}`);
  return r.json();
}
