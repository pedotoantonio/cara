import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Microphone,
  BellRinging,
  MapPin,
  Camera,
  CheckCircle,
  XCircle,
  Warning,
} from '@phosphor-icons/react';
import { Button, Card, CardTitle, CardSubtitle, Badge, useToast } from '@/design/components';
import {
  usePermissionsState,
  requestMic,
  requestCamera,
  requestNotifications,
  requestGeolocation,
  markOnboardingComplete,
  skipPermission,
  isSkipped,
  type PermissionsState,
  type PermissionStatus,
} from '@/hooks/usePermissions';
import { setupPushSubscription } from '@/api/push';

type Key = keyof PermissionsState;

interface Item {
  key: Key;
  Icon: typeof Microphone;
  title: string;
  body: string;
  accent: string;
}

const ITEMS: Item[] = [
  {
    key: 'mic',
    Icon: Microphone,
    title: 'Microfono',
    body: 'Per ascoltarti quando parli con me.',
    accent: 'text-accent-coral',
  },
  {
    key: 'notifications',
    Icon: BellRinging,
    title: 'Notifiche',
    body: 'Per ricordarti le cose importanti, anche quando l\'app è chiusa.',
    accent: 'text-accent-sun',
  },
  {
    key: 'geolocation',
    Icon: MapPin,
    title: 'Posizione',
    body: 'Per il meteo dove sei e i promemoria quando arrivi in un posto.',
    accent: 'text-accent-sky',
  },
  {
    key: 'camera',
    Icon: Camera,
    title: 'Fotocamera',
    body: 'Per riconoscerti quando torni a casa (opzionale, on-device).',
    accent: 'text-accent-lilac',
  },
];

function StatusBadge({ status }: { status: PermissionStatus }) {
  if (status === 'granted') {
    return (
      <Badge tone="grass" size="sm">
        <CheckCircle size={12} weight="fill" className="mr-1" />
        Concesso
      </Badge>
    );
  }
  if (status === 'denied') {
    return (
      <Badge tone="coral" size="sm">
        <XCircle size={12} weight="fill" className="mr-1" />
        Negato
      </Badge>
    );
  }
  if (status === 'unsupported') {
    return (
      <Badge tone="neutral" size="sm">
        Non disponibile
      </Badge>
    );
  }
  return (
    <Badge tone="sun" size="sm">
      <Warning size={12} weight="fill" className="mr-1" />
      Da concedere
    </Badge>
  );
}

export function PermissionsPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const { state, refresh } = usePermissionsState();
  const [busy, setBusy] = useState<Key | null>(null);

  // Hide items che sono "unsupported" se mai sono stati prompt
  const visibleItems = useMemo(
    () => ITEMS.filter((it) => state[it.key] !== 'unsupported' || !isSkipped(it.key)),
    [state],
  );

  useEffect(() => {
    // Initial refresh per allineare status — già fatto in usePermissionsState ma
    // dopo un grant/deny della permission API, alcuni browser non aggiornano
    // il `state` finché non ri-probiamo manualmente.
    void refresh();
  }, [refresh]);

  async function grant(key: Key) {
    setBusy(key);
    try {
      let result: PermissionStatus = 'prompt';
      if (key === 'mic') result = await requestMic();
      if (key === 'camera') result = await requestCamera();
      if (key === 'notifications') {
        result = await requestNotifications();
        if (result === 'granted') {
          // Subscribe to push subito (richiede service worker pronto)
          const pushResult = await setupPushSubscription();
          if (pushResult.status === 'subscribed') {
            toast.push({ tone: 'mint', title: 'Notifiche attive', body: 'Riceverai i miei promemoria.' });
          } else if (pushResult.status === 'no-key') {
            toast.push({
              tone: 'sun',
              title: 'Notifiche attive solo locali',
              body: 'Il backend Web Push non è configurato (VAPID mancante).',
            });
          }
        }
      }
      if (key === 'geolocation') result = await requestGeolocation();

      if (result === 'granted') {
        toast.push({ tone: 'mint', title: 'Permesso concesso' });
      } else if (result === 'denied') {
        toast.push({
          tone: 'coral',
          title: 'Permesso negato',
          body: 'Puoi cambiarlo dalle impostazioni del browser.',
        });
      }
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  function skip(key: Key) {
    skipPermission(key);
    toast.push({ tone: 'neutral', title: 'Salto per ora', body: 'Puoi riabilitarlo in qualsiasi momento.' });
    void refresh();
  }

  function finish() {
    markOnboardingComplete();
    navigate('/', { replace: true });
  }

  return (
    <main className="min-h-[100dvh] bg-bg-base">
      <div className="container-app py-8">
        <motion.header
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="text-center mb-6"
        >
          <h1 className="font-display text-3xl text-text-primary">Ti chiedo qualche permesso</h1>
          <p className="mt-2 text-text-secondary">
            Per esserti davvero d'aiuto. Puoi sempre dire di no, o riprovarci dopo.
          </p>
        </motion.header>

        <ul className="space-y-3">
          {visibleItems.map((it, i) => {
            const status = state[it.key];
            const granted = status === 'granted';
            const denied = status === 'denied';
            return (
              <motion.li
                key={it.key}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.08 * i }}
              >
                <Card padding="lg" elevation={1}>
                  <div className="flex items-start gap-3">
                    <it.Icon size={28} weight="duotone" className={it.accent} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <CardTitle>{it.title}</CardTitle>
                        <StatusBadge status={status} />
                      </div>
                      <CardSubtitle>{it.body}</CardSubtitle>
                      {!granted && status !== 'unsupported' && (
                        <div className="mt-3 flex gap-2">
                          <Button size="sm" loading={busy === it.key} onClick={() => grant(it.key)}>
                            {denied ? 'Riprova' : 'Concedi'}
                          </Button>
                          {!denied && (
                            <Button size="sm" variant="ghost" onClick={() => skip(it.key)}>
                              Salta per ora
                            </Button>
                          )}
                        </div>
                      )}
                      {denied && (
                        <p className="mt-2 text-xs text-text-muted">
                          Se hai cambiato idea: tocca "Riprova" dopo aver concesso il permesso nelle
                          impostazioni del browser.
                        </p>
                      )}
                    </div>
                  </div>
                </Card>
              </motion.li>
            );
          })}
        </ul>

        <div className="mt-8 flex flex-col gap-2">
          <Button size="lg" fullWidth onClick={finish}>
            Inizia a usare CARA
          </Button>
          <p className="text-xs text-center text-text-muted">
            Puoi cambiare questi permessi da <strong>Tu → Impostazioni</strong>.
          </p>
        </div>
      </div>
    </main>
  );
}
