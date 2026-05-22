import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, BellSlash, SignOut, ArrowLeft } from '@phosphor-icons/react';
import {
  Button,
  Card,
  CardSubtitle,
  CardTitle,
  Input,
  useToast,
} from '@/design/components';
import { useAuthStore } from '@/state/auth';
import { useAvatarStore } from '@/state/avatar';
import { updateMe, TONE_LABELS, type ToneKey } from '@/api/auth';
import {
  requestNotifications,
  usePermissionsState,
  markOnboardingComplete,
} from '@/hooks/usePermissions';
import { setupPushSubscription, unsubscribePush } from '@/api/push';

export function SettingsPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const user = useAuthStore((s) => s.user);
  const refreshMe = useAuthStore((s) => s.refreshMe);
  const logout = useAuthStore((s) => s.logout);
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  const { state: perms, refresh: refreshPerms } = usePermissionsState();

  const [fullName, setFullName] = useState(user?.full_name ?? '');
  const [birthDate, setBirthDate] = useState(user?.birth_date ?? '');
  const [tone, setTone] = useState<ToneKey>(user?.tone_preference ?? 'default');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'neutral',
      glowAccent: 'rose',
      caption: null,
      context: 'me:settings',
    });
  }, [setAvatar]);

  async function saveProfile() {
    setBusy(true);
    try {
      await updateMe({
        full_name: fullName.trim() || null,
        birth_date: birthDate || null,
        tone_preference: tone,
      });
      await refreshMe();
      toast.push({ tone: 'mint', title: 'Salvato' });
    } catch (err) {
      toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function togglePush(enable: boolean) {
    setBusy(true);
    try {
      if (enable) {
        const status = await requestNotifications();
        if (status === 'granted') {
          const r = await setupPushSubscription('user-setting');
          if (r.status === 'subscribed') {
            toast.push({ tone: 'mint', title: 'Notifiche attivate' });
          } else {
            toast.push({ tone: 'sun', title: 'Notifiche locali', body: r.detail ?? r.status });
          }
        } else {
          toast.push({
            tone: 'coral',
            title: 'Permesso non concesso',
            body: 'Cambia il permesso dalle impostazioni del browser e riprova.',
          });
        }
        await refreshPerms();
      } else {
        await unsubscribePush();
        await refreshPerms();
        toast.push({ tone: 'neutral', title: 'Notifiche disattivate' });
      }
    } finally {
      setBusy(false);
    }
  }

  function resetSwAndReload() {
    if (!confirm('Vuoi pulire la cache e ricaricare? Utile se la pagina non si aggiorna.')) return;
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.getRegistrations().then((regs) => {
        regs.forEach((r) => r.unregister());
        window.location.reload();
      });
    } else {
      window.location.reload();
    }
  }

  function resetPermissionsOnboarding() {
    // Mark NOT complete → next visit redirects to /permissions
    try {
      localStorage.removeItem('cara.permissions.asked');
    } catch {
      /* noop */
    }
    toast.push({ tone: 'sky', title: 'Riavvio onboarding', body: 'Ti chiederò di nuovo i permessi.' });
    setTimeout(() => navigate('/permissions'), 500);
  }

  async function doLogout() {
    logout();
    navigate('/login', { replace: true });
  }

  const pushActive = perms.notifications === 'granted';

  return (
    <div className="container-app py-4 space-y-4">
      <header className="flex items-center gap-2">
        <button onClick={() => navigate('/me')} className="p-2 -m-2" aria-label="Indietro">
          <ArrowLeft size={20} />
        </button>
        <h1 className="font-display text-2xl">Impostazioni</h1>
      </header>

      {/* Profilo */}
      <Card padding="lg" elevation={1}>
        <CardTitle>Profilo</CardTitle>
        <CardSubtitle>Come CARA ti conosce.</CardSubtitle>
        <div className="mt-4 space-y-3">
          <Input
            label="Nome completo"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Antonio Pedoto"
          />
          <Input
            type="date"
            label="Data di nascita"
            value={birthDate}
            onChange={(e) => setBirthDate(e.target.value)}
          />
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1.5">
              Tono della voce
            </label>
            <select
              value={tone}
              onChange={(e) => setTone(e.target.value as ToneKey)}
              className="w-full h-11 rounded-md bg-bg-base border border-border-soft px-3 text-base focus:border-accent-coral focus:ring-2 focus:ring-accent-coral/20 outline-none"
            >
              {(Object.keys(TONE_LABELS) as ToneKey[]).map((k) => (
                <option key={k} value={k}>
                  {TONE_LABELS[k].label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-text-muted">{TONE_LABELS[tone].description}</p>
          </div>
          <Button onClick={saveProfile} loading={busy} fullWidth>
            Salva profilo
          </Button>
        </div>
      </Card>

      {/* Notifiche */}
      <Card padding="lg" elevation={1}>
        <CardTitle>Notifiche</CardTitle>
        <CardSubtitle>
          {pushActive
            ? 'Riceverai i promemoria anche quando l\'app è chiusa.'
            : 'Attiva per ricevere i promemoria sul dispositivo.'}
        </CardSubtitle>
        <div className="mt-3">
          <Button
            variant={pushActive ? 'secondary' : 'primary'}
            leftIcon={pushActive ? <BellSlash size={18} /> : <Bell size={18} />}
            onClick={() => togglePush(!pushActive)}
            loading={busy}
          >
            {pushActive ? 'Disattiva notifiche' : 'Attiva notifiche'}
          </Button>
        </div>
      </Card>

      {/* App */}
      <Card padding="lg" elevation={1}>
        <CardTitle>App</CardTitle>
        <CardSubtitle>Strumenti tecnici.</CardSubtitle>
        <div className="mt-3 space-y-2">
          <Button variant="ghost" size="sm" onClick={resetSwAndReload} fullWidth>
            Pulisci cache e ricarica
          </Button>
          <Button variant="ghost" size="sm" onClick={resetPermissionsOnboarding} fullWidth>
            Riavvia onboarding permessi
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              markOnboardingComplete();
              toast.push({ tone: 'mint', title: 'Onboarding saltato' });
            }}
            fullWidth
          >
            Segna onboarding completato (silenzia popup)
          </Button>
        </div>
      </Card>

      {/* Esci */}
      <Card padding="lg" elevation={1}>
        <CardTitle>Account</CardTitle>
        <CardSubtitle>{user?.email}</CardSubtitle>
        <div className="mt-3">
          <Button variant="danger" leftIcon={<SignOut size={18} />} onClick={doLogout} fullWidth>
            Esci
          </Button>
        </div>
      </Card>

      <p className="text-center text-xs text-text-muted py-4">CARA v2.0.0 · Casa Pedoto</p>
    </div>
  );
}
