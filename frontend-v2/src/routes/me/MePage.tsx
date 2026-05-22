import { useEffect } from 'react';
import { useAvatarStore } from '@/state/avatar';
import { useAuthStore } from '@/state/auth';
import { Card, CardSubtitle, Badge, Button } from '@/design/components';
import { User, Brain, Plug, Wallet, Gear, ShieldStar, SignOut } from '@phosphor-icons/react';
import { Link } from 'react-router-dom';

export function MePage() {
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'neutral',
      glowAccent: 'rose',
      caption: null,
      context: 'me',
    });
  }, [setAvatar]);

  const sections = [
    { to: '/me/persona',      label: 'Profilo persona',  Icon: Brain,    accent: 'text-accent-lilac' },
    { to: '/me/memory',       label: 'Memoria',          Icon: Brain,    accent: 'text-accent-lilac' },
    { to: '/me/integrations', label: 'Integrazioni',     Icon: Plug,     accent: 'text-accent-grass' },
    { to: '/me/wallet',       label: 'Wallet widget',    Icon: Wallet,   accent: 'text-accent-sun' },
    { to: '/me/settings',     label: 'Impostazioni',     Icon: Gear,     accent: 'text-text-secondary' },
  ];

  return (
    <div className="container-app py-6 space-y-4">
      <header className="flex items-center gap-4 mb-2">
        <div className="w-16 h-16 rounded-full bg-accent-rose/30 grid place-items-center">
          <User size={28} weight="fill" className="text-accent-rose" />
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="font-display text-2xl truncate">{user?.full_name ?? user?.email}</h1>
          <div className="mt-1 flex items-center gap-2">
            <Badge tone="rose" size="sm">{user?.role ?? 'guest'}</Badge>
            {user?.is_admin && <Badge tone="coral" size="sm">admin</Badge>}
          </div>
        </div>
      </header>

      <div className="space-y-2">
        {sections.map(({ to, label, Icon, accent }) => (
          <Link key={to} to={to}>
            <Card padding="base" elevation={0} className="flex items-center gap-4 hover:bg-bg-surface transition-colors duration-quick">
              <Icon size={24} weight="duotone" className={accent} />
              <span className="flex-1 font-medium">{label}</span>
              <span className="text-text-muted">›</span>
            </Card>
          </Link>
        ))}
        {user?.is_admin && (
          <Link to="/admin">
            <Card padding="base" elevation={0} className="flex items-center gap-4 hover:bg-bg-surface transition-colors duration-quick">
              <ShieldStar size={24} weight="duotone" className="text-accent-coral" />
              <span className="flex-1 font-medium">Amministrazione</span>
              <span className="text-text-muted">›</span>
            </Card>
          </Link>
        )}
      </div>

      <div className="pt-4">
        <Button variant="ghost" leftIcon={<SignOut size={18} />} onClick={logout} fullWidth>
          Esci
        </Button>
      </div>

      <footer className="pt-6 text-center">
        <CardSubtitle>CARA v2.0.0 · Casa Pedoto</CardSubtitle>
      </footer>
    </div>
  );
}
