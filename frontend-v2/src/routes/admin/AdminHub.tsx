import { useEffect } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import {
  ShieldStar,
  Users,
  Brain,
  Lightning,
  HouseSimple,
  Robot,
  TelegramLogo,
  Stethoscope,
  Sparkle,
  DeviceMobile,
  ArrowSquareOut,
  ArrowLeft,
} from '@phosphor-icons/react';
import { useAuthStore } from '@/state/auth';
import { useAvatarStore } from '@/state/avatar';
import { Card, CardSubtitle, CardTitle } from '@/design/components';

const V1_BASE = 'https://192.168.1.23:8455';

const LINKS = [
  { url: '/admin', label: 'Pannello admin', Icon: ShieldStar, body: 'Feature flags, prompt, voce, audit' },
  { url: '/admin/users', label: 'Famiglia', Icon: Users, body: 'Aggiungi membri, ruoli, permessi' },
  { url: '/admin/persona', label: 'Profili Persona', Icon: Brain, body: 'Vedi e rigenera i profili LLM' },
  { url: '/admin/memory', label: 'Memoria', Icon: Brain, body: 'Fatti memorizzati per utente' },
  { url: '/admin/face', label: 'Riconoscimento volti', Icon: HouseSimple, body: 'Enroll, soglie, attivazione' },
  { url: '/admin/smart-home', label: 'Smart Home', Icon: Lightning, body: 'Home Assistant, dispositivi' },
  { url: '/admin/proactivity', label: 'Proattività', Icon: Sparkle, body: 'Regole + suggerimenti' },
  { url: '/admin/skills', label: 'Skill Factory', Icon: Robot, body: 'Skill data-driven + dispatcher' },
  { url: '/admin/telegram', label: 'Telegram bot', Icon: TelegramLogo, body: 'Mappings chat ↔ utenti' },
  { url: '/admin/devices', label: 'Dispositivi', Icon: DeviceMobile, body: 'Pairing wall/mobile' },
  { url: '/admin/diagnostics', label: 'Diagnostica', Icon: Stethoscope, body: 'Health checks live' },
];

export function AdminHub() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const setAvatar = useAvatarStore((s) => s.setAvatar);

  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'neutral',
      glowAccent: 'coral',
      caption: null,
      context: 'admin',
    });
  }, [setAvatar]);

  if (!user?.is_admin) {
    return <Navigate to="/me" replace />;
  }

  return (
    <div className="container-app py-4 space-y-4">
      <header className="flex items-center gap-2">
        <button onClick={() => navigate('/me')} className="p-2 -m-2" aria-label="Indietro">
          <ArrowLeft size={20} />
        </button>
        <h1 className="font-display text-2xl">Amministrazione</h1>
      </header>

      <Card padding="lg" surface="surface" elevation={0}>
        <CardTitle>Pagine admin avanzate</CardTitle>
        <CardSubtitle className="mt-1">
          Per ora le pagine admin sono sulla v1 di CARA (porta 8455). I link qui sotto le aprono
          in una nuova scheda. Quando saranno riscritte qui, l'esperienza sarà nativa.
        </CardSubtitle>
      </Card>

      <ul className="space-y-2">
        {LINKS.map(({ url, label, Icon, body }) => (
          <li key={url}>
            <a href={`${V1_BASE}${url}`} target="_blank" rel="noopener noreferrer" className="block">
              <Card padding="base" elevation={1} className="hover:border-accent-coral/40 transition-colors">
                <div className="flex items-center gap-3">
                  <Icon size={24} weight="duotone" className="text-accent-coral flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="font-medium">{label}</p>
                    <CardSubtitle>{body}</CardSubtitle>
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
