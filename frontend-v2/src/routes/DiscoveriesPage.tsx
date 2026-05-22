import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Compass,
  Radio,
  Newspaper,
  VideoCamera,
  Microphone,
  Image as ImageIcon,
  FileText,
  ArrowSquareOut,
  ThumbsUp,
  ThumbsDown,
} from '@phosphor-icons/react';
import { Card, CardSubtitle, Badge, Skeleton, Button } from '@/design/components';
import { useAvatarStore } from '@/state/avatar';
import { listCdaItems, feedbackCda, type CdaKind, type CdaItem } from '@/api/cda';
import { cn } from '@/lib/cn';

const KIND_META: Record<CdaKind, { label: string; Icon: typeof Radio; accent: string }> = {
  radio:    { label: 'Radio',    Icon: Radio,        accent: 'clay' },
  article:  { label: 'Articoli', Icon: Newspaper,    accent: 'clay' },
  video:    { label: 'Video',    Icon: VideoCamera,  accent: 'lilac' },
  podcast:  { label: 'Podcast',  Icon: Microphone,   accent: 'mint' },
  image:    { label: 'Immagini', Icon: ImageIcon,    accent: 'sky' },
  document: { label: 'Documenti',Icon: FileText,     accent: 'sun' },
};

const KINDS: CdaKind[] = ['radio', 'article', 'video', 'podcast', 'image', 'document'];

export function DiscoveriesPage() {
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<CdaKind | 'all'>('all');

  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'thoughtful',
      glowAccent: 'lilac',
      caption: null,
      context: 'discoveries',
    });
  }, [setAvatar]);

  const itemsQ = useQuery({
    queryKey: ['cda.items', filter],
    queryFn: () => (filter === 'all' ? listCdaItems(undefined, true) : listCdaItems(filter, true)),
    staleTime: 60_000,
  });

  const feedbackM = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'like' | 'dislike' }) =>
      feedbackCda(id, action),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['cda.items'] });
    },
  });

  return (
    <div className="container-app py-4 space-y-4">
      <header className="flex items-center gap-2">
        <Link to="/me" className="p-2 -m-2" aria-label="Indietro">
          ←
        </Link>
        <h1 className="font-display text-2xl">Scoperte</h1>
      </header>

      <Card padding="base" surface="surface" elevation={0}>
        <div className="flex items-start gap-3">
          <Compass size={24} weight="duotone" className="text-accent-lilac" />
          <CardSubtitle>
            Contenuti che ho trovato per voi quando chiedete cose come "trova una radio jazz" o
            "cerca un articolo su...". Si auto-puliscono quando perdono qualità.
          </CardSubtitle>
        </div>
      </Card>

      <nav className="flex overflow-x-auto no-scrollbar gap-2">
        <button
          onClick={() => setFilter('all')}
          className={cn(
            'px-3 py-1.5 rounded-pill text-sm font-medium whitespace-nowrap border transition-colors',
            filter === 'all'
              ? 'bg-text-primary text-text-inverse border-text-primary'
              : 'bg-bg-base text-text-secondary border-border-soft',
          )}
        >
          Tutto
        </button>
        {KINDS.map((k) => (
          <button
            key={k}
            onClick={() => setFilter(k)}
            className={cn(
              'px-3 py-1.5 rounded-pill text-sm font-medium whitespace-nowrap border transition-colors',
              filter === k
                ? 'bg-text-primary text-text-inverse border-text-primary'
                : 'bg-bg-base text-text-secondary border-border-soft',
            )}
          >
            {KIND_META[k].label}
          </button>
        ))}
      </nav>

      {itemsQ.isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      )}

      {!itemsQ.isLoading && (itemsQ.data?.length ?? 0) === 0 && (
        <p className="text-text-muted text-center py-8 text-sm">
          Niente da mostrare. Chiedimi qualcosa come "trova una radio jazz" e qui apparirà.
        </p>
      )}

      <ul className="space-y-2">
        {itemsQ.data?.map((it: CdaItem) => {
          const meta = KIND_META[it.kind];
          const Icon = meta.Icon;
          return (
            <li key={it.id}>
              <Card padding="base" elevation={1}>
                <div className="flex items-start gap-3">
                  <Icon size={24} weight="duotone" className={`text-accent-${meta.accent} flex-shrink-0 mt-1`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge tone={meta.accent as 'clay' | 'lilac' | 'mint' | 'sky' | 'sun'} size="sm">
                        {meta.label}
                      </Badge>
                      <CardSubtitle>conf {Math.round(it.confidence * 100)}%</CardSubtitle>
                    </div>
                    <a
                      href={it.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-medium text-text-primary hover:text-accent-coral inline-flex items-center gap-1"
                    >
                      {it.title}
                      <ArrowSquareOut size={14} />
                    </a>
                    {it.source && <CardSubtitle>{it.source}</CardSubtitle>}
                    {it.description && (
                      <p className="text-sm text-text-secondary line-clamp-2 mt-1">
                        {it.description}
                      </p>
                    )}
                    <div className="mt-2 flex gap-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        leftIcon={<ThumbsUp size={14} />}
                        onClick={() => feedbackM.mutate({ id: it.id, action: 'like' })}
                      >
                        Mi piace
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        leftIcon={<ThumbsDown size={14} />}
                        onClick={() => feedbackM.mutate({ id: it.id, action: 'dislike' })}
                      >
                        Nope
                      </Button>
                    </div>
                  </div>
                </div>
              </Card>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
