import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  GoogleLogo,
  Calendar,
  Envelope,
  CheckCircle,
  XCircle,
  ArrowsClockwise,
  Link as LinkIcon,
} from '@phosphor-icons/react';
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
  getGoogleStatus,
  startGoogleOAuth,
  disconnectGoogle,
  syncGoogleNow,
} from '@/api/integrations';

export function IntegrationsPage() {
  const navigate = useNavigate();
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  const toast = useToast();
  const queryClient = useQueryClient();

  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'neutral',
      glowAccent: 'grass',
      caption: null,
      context: 'me:integrations',
    });
  }, [setAvatar]);

  const statusQ = useQuery({
    queryKey: ['integrations.google'],
    queryFn: getGoogleStatus,
    staleTime: 30_000,
  });

  const connectM = useMutation({
    mutationFn: () => startGoogleOAuth(),
    onSuccess: (res) => {
      if (res.url) {
        window.location.href = res.url;
      } else {
        toast.push({
          tone: 'sun',
          title: 'OAuth non configurato',
          body: 'L\'admin deve impostare le credenziali Google in /admin/integrations.',
        });
      }
    },
  });

  const disconnectM = useMutation({
    mutationFn: () => disconnectGoogle(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['integrations.google'] });
      toast.push({ tone: 'neutral', title: 'Google scollegato' });
    },
    onError: (err) => toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message }),
  });

  const syncM = useMutation({
    mutationFn: () => syncGoogleNow(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['integrations.google'] });
      toast.push({ tone: 'mint', title: 'Sincronizzazione avviata' });
    },
  });

  const g = statusQ.data;

  return (
    <div className="container-app py-4 space-y-4">
      <header className="flex items-center gap-2">
        <button onClick={() => navigate('/me')} className="p-2 -m-2" aria-label="Indietro">
          <ArrowLeft size={20} />
        </button>
        <h1 className="font-display text-2xl">Integrazioni</h1>
      </header>

      <Card padding="lg" elevation={1}>
        <div className="flex items-center gap-3 mb-3">
          <GoogleLogo size={28} weight="duotone" className="text-accent-grass" />
          <div className="flex-1 min-w-0">
            <CardTitle>Google</CardTitle>
            {statusQ.isLoading ? (
              <Skeleton variant="text" className="w-32 mt-1" />
            ) : g?.connected ? (
              <CardSubtitle>{g.email}</CardSubtitle>
            ) : (
              <CardSubtitle>Non collegato</CardSubtitle>
            )}
          </div>
          {g?.connected ? (
            <Badge tone="grass">
              <CheckCircle size={12} weight="fill" className="mr-1" />
              Collegato
            </Badge>
          ) : (
            <Badge tone="neutral">
              <XCircle size={12} weight="fill" className="mr-1" />
              Disconnesso
            </Badge>
          )}
        </div>

        {g?.connected && (
          <ul className="text-sm space-y-1 mb-3">
            <li className="flex items-center gap-2">
              <Calendar size={16} weight="duotone" className="text-accent-sky" />
              Google Calendar:{' '}
              <strong>{g.calendar_enabled ? 'attivo' : 'non attivo'}</strong>
            </li>
            <li className="flex items-center gap-2">
              <Envelope size={16} weight="duotone" className="text-accent-clay" />
              Gmail:{' '}
              <strong>{g.gmail_enabled ? 'attivo' : 'non attivo'}</strong>
            </li>
            {g.last_sync_at && (
              <li className="text-xs text-text-muted mt-1">
                Ultima sincronizzazione: {new Date(g.last_sync_at).toLocaleString('it-IT')}
              </li>
            )}
          </ul>
        )}

        <div className="flex gap-2 flex-wrap">
          {!g?.connected ? (
            <Button
              leftIcon={<LinkIcon size={18} />}
              onClick={() => connectM.mutate()}
              loading={connectM.isPending}
            >
              Collega Google
            </Button>
          ) : (
            <>
              <Button
                size="sm"
                variant="secondary"
                leftIcon={<ArrowsClockwise size={16} />}
                onClick={() => syncM.mutate()}
                loading={syncM.isPending}
              >
                Sincronizza ora
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  if (window.confirm('Scollegare Google? Le sincronizzazioni si fermeranno.')) {
                    disconnectM.mutate();
                  }
                }}
              >
                Scollega
              </Button>
            </>
          )}
        </div>
      </Card>

      <Card padding="lg" surface="surface" elevation={0}>
        <CardTitle>Altre integrazioni</CardTitle>
        <CardSubtitle className="mt-1">
          Telegram, Home Assistant, Frigate, Notifiche push sono già configurati da Antonio
          (admin) e funzionano automaticamente — non serve fare nulla qui.
        </CardSubtitle>
      </Card>
    </div>
  );
}
