import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  CheckCircle,
  Warning,
  XCircle,
  Question,
  ArrowsClockwise,
} from '@phosphor-icons/react';
import {
  Button,
  Card,
  CardSubtitle,
  CardTitle,
  Skeleton,
} from '@/design/components';
import { useAvatarStore } from '@/state/avatar';
import { fetchDiagnostics, type DiagnosticItem } from '@/api/diagnostics';

function statusIcon(s: DiagnosticItem['status']) {
  if (s === 'ok') return <CheckCircle size={20} weight="fill" className="text-accent-grass" />;
  if (s === 'warn') return <Warning size={20} weight="fill" className="text-accent-sun" />;
  if (s === 'fail') return <XCircle size={20} weight="fill" className="text-accent-coral" />;
  return <Question size={20} weight="fill" className="text-text-muted" />;
}

export function DiagnosticsPage() {
  const navigate = useNavigate();
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  const queryClient = useQueryClient();

  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'thoughtful',
      glowAccent: 'sky',
      caption: null,
      context: 'diagnostics',
    });
  }, [setAvatar]);

  const q = useQuery({
    queryKey: ['diagnostics'],
    queryFn: fetchDiagnostics,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const items = q.data?.items ?? [];
  const counts = {
    ok: items.filter((x) => x.status === 'ok').length,
    warn: items.filter((x) => x.status === 'warn').length,
    fail: items.filter((x) => x.status === 'fail').length,
    unknown: items.filter((x) => x.status === 'unknown').length,
  };

  return (
    <div className="container-app py-4 space-y-4">
      <header className="flex items-center gap-2">
        <button onClick={() => navigate(-1)} className="p-2 -m-2" aria-label="Indietro">
          <ArrowLeft size={20} />
        </button>
        <h1 className="font-display text-2xl">Diagnostica</h1>
        <Button
          variant="ghost"
          size="sm"
          leftIcon={<ArrowsClockwise size={16} />}
          onClick={() => queryClient.invalidateQueries({ queryKey: ['diagnostics'] })}
          className="ml-auto"
        >
          Aggiorna
        </Button>
      </header>

      <Card padding="lg" surface="surface" elevation={0}>
        <div className="grid grid-cols-4 gap-2 text-center">
          <div>
            <p className="text-2xl font-display text-accent-grass">{counts.ok}</p>
            <CardSubtitle>OK</CardSubtitle>
          </div>
          <div>
            <p className="text-2xl font-display text-accent-sun">{counts.warn}</p>
            <CardSubtitle>Avvisi</CardSubtitle>
          </div>
          <div>
            <p className="text-2xl font-display text-accent-coral">{counts.fail}</p>
            <CardSubtitle>Errori</CardSubtitle>
          </div>
          <div>
            <p className="text-2xl font-display text-text-muted">{counts.unknown}</p>
            <CardSubtitle>Sconosciuti</CardSubtitle>
          </div>
        </div>
        {q.data && (
          <CardSubtitle className="text-center mt-2">
            Aggiornato: {new Date(q.data.generated_at).toLocaleTimeString('it-IT')}
          </CardSubtitle>
        )}
      </Card>

      {q.isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {!q.isLoading && items.length === 0 && (
        <p className="text-text-muted text-center py-8 text-sm">
          Nessun check disponibile.
        </p>
      )}

      <ul className="space-y-2">
        {items.map((it, i) => (
          <li key={`${it.name}-${i}`}>
            <Card padding="base" elevation={1}>
              <div className="flex items-center gap-3">
                {statusIcon(it.status)}
                <div className="flex-1 min-w-0">
                  <CardTitle>{it.name}</CardTitle>
                  {it.detail && <CardSubtitle>{it.detail}</CardSubtitle>}
                </div>
                {it.duration_ms != null && (
                  <span className="text-xs text-text-muted whitespace-nowrap">
                    {it.duration_ms} ms
                  </span>
                )}
              </div>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
