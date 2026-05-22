import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Brain, ArrowsClockwise, Trash, ArrowLeft } from '@phosphor-icons/react';
import {
  Button,
  Card,
  CardSubtitle,
  CardTitle,
  Badge,
  Skeleton,
  useToast,
} from '@/design/components';
import { useAvatarStore } from '@/state/avatar';
import {
  getMyPersona,
  rebuildMyPersona,
  deleteMyPersona,
  type PersonaProfile,
} from '@/api/persona';

export function PersonaPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'thoughtful',
      glowAccent: 'lilac',
      caption: null,
      context: 'me:persona',
    });
  }, [setAvatar]);

  const personaQ = useQuery({
    queryKey: ['persona.me'],
    queryFn: getMyPersona,
    staleTime: 60_000,
  });

  const rebuildM = useMutation({
    mutationFn: () => rebuildMyPersona(),
    onSuccess: (res) => {
      void queryClient.invalidateQueries({ queryKey: ['persona.me'] });
      toast.push({
        tone: res.status === 'ok' ? 'mint' : 'sun',
        title: 'Profilo aggiornato',
        body: `${res.chunks_processed ?? 0} chunk · conf ${res.confidence ?? '?'}%`,
      });
    },
    onError: (err) => {
      const msg = (err as Error).message;
      if (msg.includes('retry in') || msg.includes('429')) {
        toast.push({ tone: 'sun', title: 'Aspetta ancora un po\'', body: msg });
      } else {
        toast.push({ tone: 'coral', title: 'Errore', body: msg });
      }
    },
  });

  const deleteM = useMutation({
    mutationFn: () => deleteMyPersona(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['persona.me'] });
      toast.push({ tone: 'neutral', title: 'Profilo cancellato' });
      setConfirmDelete(false);
    },
    onError: (err) =>
      toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message }),
  });

  const p: PersonaProfile | null | undefined = personaQ.data;

  function statusBadge() {
    if (!p?.last_status) return <Badge tone="neutral">Mai costruito</Badge>;
    if (p.last_status === 'ok') return <Badge tone="grass">OK</Badge>;
    if (p.last_status === 'low_confidence') return <Badge tone="sun">Bassa confidenza</Badge>;
    if (p.last_status === 'failed') return <Badge tone="coral">Errore</Badge>;
    return <Badge tone="neutral">{p.last_status}</Badge>;
  }

  return (
    <div className="container-app py-4 space-y-4">
      <header className="flex items-center gap-2">
        <button onClick={() => navigate('/me')} className="p-2 -m-2" aria-label="Indietro">
          <ArrowLeft size={20} />
        </button>
        <h1 className="font-display text-2xl">Profilo persona</h1>
      </header>

      <Card padding="lg" surface="surface" elevation={0}>
        <div className="flex items-start gap-3">
          <Brain size={28} weight="duotone" className="text-accent-lilac" />
          <div className="flex-1">
            <p className="text-sm text-text-secondary">
              CARA costruisce un riassunto di chi sei dalle conversazioni che facciamo insieme.
              Lo usa per parlarti in modo più personale.
            </p>
            <p className="text-xs text-text-muted mt-2">
              Si aggiorna automaticamente di notte. Puoi anche chiedere di aggiornarlo subito.
            </p>
          </div>
        </div>
      </Card>

      {personaQ.isLoading && <Skeleton className="h-48 w-full" />}

      {!personaQ.isLoading && (!p || !p.markdown) && (
        <Card padding="lg" elevation={1}>
          <CardTitle>Niente da mostrare ancora</CardTitle>
          <CardSubtitle>
            Conversiamo un po' e ti farò un profilo. Oppure chiedimelo subito.
          </CardSubtitle>
          <div className="mt-3">
            <Button
              leftIcon={<ArrowsClockwise size={18} />}
              onClick={() => rebuildM.mutate()}
              loading={rebuildM.isPending}
            >
              Costruisci ora
            </Button>
          </div>
        </Card>
      )}

      {p && p.markdown && (
        <>
          <Card padding="lg" elevation={1}>
            <div className="flex items-center justify-between gap-2 mb-2">
              <CardTitle>Stato</CardTitle>
              {statusBadge()}
            </div>
            <div className="text-sm text-text-secondary space-y-1">
              <p>
                Confidenza: <strong className="text-text-primary">{p.confidence ?? '—'}%</strong>
              </p>
              <p>
                Ultimo aggiornamento:{' '}
                {p.last_built_at
                  ? new Date(p.last_built_at).toLocaleString('it-IT', {
                      day: '2-digit',
                      month: 'short',
                      hour: '2-digit',
                      minute: '2-digit',
                    })
                  : 'mai'}
              </p>
              <p>{p.markdown.length} caratteri</p>
            </div>
            {p.last_error && (
              <p className="mt-2 text-xs text-accent-coral">Ultimo errore: {p.last_error}</p>
            )}
            <div className="mt-3 flex gap-2 flex-wrap">
              <Button
                leftIcon={<ArrowsClockwise size={18} />}
                onClick={() => rebuildM.mutate()}
                loading={rebuildM.isPending}
                size="sm"
              >
                Aggiorna ora
              </Button>
              <Button
                variant="danger"
                leftIcon={<Trash size={18} />}
                onClick={() => (confirmDelete ? deleteM.mutate() : setConfirmDelete(true))}
                loading={deleteM.isPending}
                size="sm"
              >
                {confirmDelete ? 'Confermi?' : 'Cancella mio profilo'}
              </Button>
            </div>
          </Card>

          <Card padding="lg" elevation={1}>
            <CardTitle>Quello che so di te</CardTitle>
            <pre className="mt-3 whitespace-pre-wrap break-words text-sm text-text-primary leading-relaxed font-ui">
              {p.markdown}
            </pre>
          </Card>
        </>
      )}
    </div>
  );
}
