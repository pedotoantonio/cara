import { useQuery } from '@tanstack/react-query';
import { Newspaper, ArrowSquareOut } from '@phosphor-icons/react';
import { Card, CardSubtitle, Skeleton, Badge } from '@/design/components';
import { apiGet } from '@/api/client';

interface NewsItem {
  id?: string;
  title: string;
  link: string;
  source?: string;
  published?: string | null;
  category?: string;
  summary?: string;
}

interface NewsResponse {
  items?: NewsItem[];
}

async function fetchNews(): Promise<NewsItem[]> {
  try {
    const r = await apiGet<NewsResponse | NewsItem[]>(`/news?limit=30`);
    if (Array.isArray(r)) return r;
    return r.items ?? [];
  } catch {
    return [];
  }
}

export function NewsPage() {
  const q = useQuery({ queryKey: ['news.list'], queryFn: fetchNews, staleTime: 5 * 60_000 });

  return (
    <div className="container-app py-4 space-y-3">
      {q.isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      )}

      {!q.isLoading && q.data?.length === 0 && (
        <Card padding="lg" surface="surface" elevation={0}>
          <div className="text-center py-6">
            <Newspaper size={32} weight="duotone" className="text-text-muted mx-auto" />
            <p className="mt-3 text-sm text-text-secondary">
              Le notizie non sono disponibili adesso.
            </p>
            <p className="mt-1 text-xs text-text-muted">
              Probabilmente la funzione è disattivata in <strong>/admin</strong> o il feed RSS è
              temporaneamente offline.
            </p>
          </div>
        </Card>
      )}

      <ul className="space-y-2">
        {q.data?.map((item, i) => (
          <li key={item.id ?? `${item.link}-${i}`}>
            <a href={item.link} target="_blank" rel="noopener noreferrer" className="block">
              <Card padding="base" elevation={1} className="hover:border-accent-clay/40 transition-colors">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    {item.category && (
                      <Badge tone="clay" size="sm" className="mb-1">
                        {item.category}
                      </Badge>
                    )}
                    <p className="font-medium leading-tight">{item.title}</p>
                    {item.summary && (
                      <p className="text-sm text-text-secondary mt-1 line-clamp-2">{item.summary}</p>
                    )}
                    <CardSubtitle className="mt-1">
                      {item.source}
                      {item.published && (
                        <> · {new Date(item.published).toLocaleString('it-IT', {
                          day: '2-digit',
                          month: 'short',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}</>
                      )}
                    </CardSubtitle>
                  </div>
                  <ArrowSquareOut size={18} className="text-text-muted flex-shrink-0" />
                </div>
              </Card>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
