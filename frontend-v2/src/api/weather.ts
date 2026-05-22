import { apiGet } from './client';

export interface WeatherDaily {
  date: string;
  temperature_max: number;
  temperature_min: number;
  icon_slug: string;
  label: string;
  precipitation_mm: number;
}

export interface WeatherForecast {
  city: string;
  daily: WeatherDaily[];
}

export async function fetchForecast(lat: number, lon: number): Promise<WeatherForecast | null> {
  try {
    return await apiGet<WeatherForecast>(`/weather/forecast?lat=${lat}&lon=${lon}&days=7`);
  } catch {
    return null;
  }
}
