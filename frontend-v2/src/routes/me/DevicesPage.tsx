import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  DeviceMobile,
  Television,
  Watch,
  Desktop,
  HouseSimple,
  Plus,
  Trash,
} from '@phosphor-icons/react';
import {
  Button,
  Card,
  CardSubtitle,
  CardTitle,
  Skeleton,
  Badge,
  useToast,
} from '@/design/components';
import { useAvatarStore } from '@/state/avatar';
import { listDevices, pairStart, removeDevice, type Device } from '@/api/devices';

const SURFACE_ICON: Record<string, typeof DeviceMobile> = {
  mobile: DeviceMobile,
  desktop: Desktop,
  tv: Television,
  watch: Watch,
  wall: HouseSimple,
};

export function DevicesPage() {
  const navigate = useNavigate();
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  const toast = useToast();
  const queryClient = useQueryClient();
  const [pairing, setPairing] = useState<{ code: string; expires_at: string } | null>(null);

  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'neutral',
      glowAccent: 'sky',
      caption: null,
      context: 'me:devices',
    });
  }, [setAvatar]);

  const q = useQuery({
    queryKey: ['devices'],
    queryFn: listDevices,
    staleTime: 30_000,
  });

  const startM = useMutation({
    mutationFn: () => pairStart(),
    onSuccess: (res) => setPairing(res),
    onError: (err) => toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message }),
  });

  const removeM = useMutation({
    mutationFn: (id: number) => removeDevice(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['devices'] });
      toast.push({ tone: 'mint', title: 'Dispositivo rimosso' });
    },
  });

  return (
    <div className="container-app py-4 space-y-4">
      <header className="flex items-center gap-2">
        <button onClick={() => navigate('/me')} className="p-2 -m-2" aria-label="Indietro">
          <ArrowLeft size={20} />
        </button>
        <h1 className="font-display text-2xl">Dispositivi</h1>
      </header>

      <Card padding="base" surface="surface" elevation={0}>
        <CardSubtitle>
          I dispositivi collegati al tuo account: telefono, tablet, display da parete.
        </CardSubtitle>
      </Card>

      <Button leftIcon={<Plus size={18} />} onClick={() => startM.mutate()} loading={startM.isPending}>
        Aggiungi dispositivo
      </Button>

      {pairing && (
        <Card padding="lg" elevation={2}>
          <CardTitle>Codice pairing</CardTitle>
          <CardSubtitle>
            Inserisci questo codice sul dispositivo da collegare. Scade alle{' '}
            {new Date(pairing.expires_at).toLocaleTimeString('it-IT')}.
          </CardSubtitle>
          <p className="font-mono text-4xl font-bold text-center mt-4 tracking-widest text-accent-coral">
            {pairing.code}
          </p>
          <div className="mt-3 flex justify-center">
            <Button variant="ghost" size="sm" onClick={() => setPairing(null)}>
              Chiudi
            </Button>
          </div>
        </Card>
      )}

      {q.isLoading && (
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {!q.isLoading && (q.data?.length ?? 0) === 0 && !pairing && (
        <p className="text-text-muted text-center py-8 text-sm">
          Nessun dispositivo collegato.
        </p>
      )}

      <ul className="space-y-2">
        {q.data?.map((d: Device) => {
          const Icon = SURFACE_ICON[d.surface] ?? DeviceMobile;
          return (
            <li key={d.id}>
              <Card padding="base" elevation={1}>
                <div className="flex items-center gap-3">
                  <Icon size={24} weight="duotone" className="text-accent-sky flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{d.label}</p>
                    <CardSubtitle>
                      {d.surface}{' '}
                      {d.last_seen_at && (
                        <span>
                          · ultimo accesso{' '}
                          {new Date(d.last_seen_at).toLocaleDateString('it-IT', {
                            day: '2-digit',
                            month: 'short',
                          })}
                        </span>
                      )}
                    </CardSubtitle>
                  </div>
                  {!d.active && (
                    <Badge tone="neutral" size="sm">
                      inattivo
                    </Badge>
                  )}
                  <button
                    onClick={() => {
                      if (window.confirm(`Rimuovere "${d.label}"?`)) removeM.mutate(d.id);
                    }}
                    className="p-2 text-text-muted hover:text-accent-coral"
                    aria-label="Rimuovi"
                  >
                    <Trash size={16} />
                  </button>
                </div>
              </Card>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
