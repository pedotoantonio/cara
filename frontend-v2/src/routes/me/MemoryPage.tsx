import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Trash, DownloadSimple, ArrowLeft, BookmarkSimple } from '@phosphor-icons/react';
import {
  Button,
  Card,
  CardSubtitle,
  Badge,
  Skeleton,
  useToast,
} from '@/design/components';
import { useAvatarStore } from '@/state/avatar';
import {
  deactivateFact,
  exportMyMemory,
  listMyFacts,
  purgeMyMemory,
  type Fact,
} from '@/api/memory';

export function MemoryPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  const [confirmPurge, setConfirmPurge] = useState(0);

  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'neutral',
      glowAccent: 'lilac',
      caption: null,
      context: 'me:memory',
    });
  }, [setAvatar]);

  const factsQ = useQuery({
    queryKey: ['memory.facts.mine'],
    queryFn: listMyFacts,
    staleTime: 60_000,
  });

  const deactivateM = useMutation({
    mutationFn: (id: number) => deactivateFact(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ['memory.facts.mine'] });
      const prev = queryClient.getQueryData<Fact[]>(['memory.facts.mine']);
      queryClient.setQueryData<Fact[]>(['memory.facts.mine'], (p) =>
        p ? p.filter((f) => f.id !== id) : p,
      );
      return { prev };
    },
    onError: (err, _id, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['memory.facts.mine'], ctx.prev);
      toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message });
    },
  });

  const purgeM = useMutation({
    mutationFn: () => purgeMyMemory(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['memory.facts.mine'] });
      toast.push({ tone: 'neutral', title: 'Memoria cancellata' });
      setConfirmPurge(0);
    },
  });

  async function doExport() {
    try {
      const data = await exportMyMemory();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `cara-memory-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.push({ tone: 'mint', title: 'Esportato' });
    } catch (err) {
      toast.push({ tone: 'coral', title: 'Errore export', body: (err as Error).message });
    }
  }

  const facts = factsQ.data ?? [];
  const grouped: Record<string, Fact[]> = {};
  for (const f of facts) {
    grouped[f.fact_type] = grouped[f.fact_type] ?? [];
    grouped[f.fact_type]!.push(f);
  }

  const TYPE_LABELS: Record<string, string> = {
    preference: 'Preferenze',
    allergy: 'Allergie',
    habit: 'Abitudini',
    personal: 'Personali',
    schedule: 'Orari',
  };

  return (
    <div className="container-app py-4 space-y-4">
      <header className="flex items-center gap-2">
        <button onClick={() => navigate('/me')} className="p-2 -m-2" aria-label="Indietro">
          <ArrowLeft size={20} />
        </button>
        <h1 className="font-display text-2xl">Memoria</h1>
      </header>

      <Card padding="lg" surface="surface" elevation={0}>
        <div className="flex items-start gap-3">
          <BookmarkSimple size={28} weight="duotone" className="text-accent-lilac" />
          <div className="flex-1">
            <p className="text-sm text-text-secondary">
              Sono i fatti che CARA ha imparato di te (preferenze, allergie, abitudini). Puoi
              vederli, eliminarli, esportarli o cancellare tutto.
            </p>
          </div>
        </div>
      </Card>

      <div className="flex gap-2 flex-wrap">
        <Button leftIcon={<DownloadSimple size={18} />} onClick={doExport} size="sm">
          Esporta JSON
        </Button>
        <Button
          variant="danger"
          leftIcon={<Trash size={18} />}
          size="sm"
          onClick={() => {
            if (confirmPurge >= 1) purgeM.mutate();
            else {
              setConfirmPurge(1);
              window.setTimeout(() => setConfirmPurge(0), 4000);
            }
          }}
          loading={purgeM.isPending}
        >
          {confirmPurge >= 1 ? 'Confermi? cancello tutto' : 'Cancella tutta la mia memoria'}
        </Button>
      </div>

      {factsQ.isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {!factsQ.isLoading && facts.length === 0 && (
        <p className="text-text-muted text-center py-8 text-sm">
          Nessun fatto memorizzato ancora.
        </p>
      )}

      {Object.keys(grouped).map((type) => (
        <section key={type}>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted mb-2 px-1">
            {TYPE_LABELS[type] ?? type} ({grouped[type]!.length})
          </h2>
          <ul className="space-y-2">
            {grouped[type]!.map((f) => (
              <li key={f.id}>
                <Card padding="base" elevation={1}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm">{f.text}</p>
                      <div className="mt-1 flex items-center gap-2">
                        <Badge tone="lilac" size="sm">
                          {f.source}
                        </Badge>
                        <CardSubtitle>conf {Math.round(f.confidence * 100)}%</CardSubtitle>
                      </div>
                    </div>
                    <button
                      onClick={() => deactivateM.mutate(f.id)}
                      className="text-text-muted hover:text-accent-coral p-2 -m-2"
                      aria-label="Disattiva"
                    >
                      <Trash size={18} />
                    </button>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
