import { authFetch } from './auth';

const API = '/api/v1';

export type NewsCategory = 'all' | 'italia' | 'mondo' | 'economia' | 'tech' | 'sport';

export interface NewsItem {
  title: string;
  summary: string;
  link: string;
  source: string;
  published: string | null;
}

export interface NewsResponse {
  category: NewsCategory;
  count: number;
  items: NewsItem[];
  digest: string;
}

export class NewsDisabledError extends Error {}

export async function getNews(category: NewsCategory = 'all', limit = 15): Promise<NewsResponse> {
  const r = await authFetch(`${API}/news?category=${category}&limit=${limit}`);
  if (r.status === 503) throw new NewsDisabledError('Le news sono disabilitate (admin).');
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
