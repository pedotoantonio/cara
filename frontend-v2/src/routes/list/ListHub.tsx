import { useEffect } from 'react';
import { useAvatarStore } from '@/state/avatar';
import { Card, CardTitle, CardSubtitle } from '@/design/components';
import { CheckSquare, ShoppingCart, Note, Bell } from '@phosphor-icons/react';
import { Link } from 'react-router-dom';

const TABS = [
  { to: 'tasks',     label: 'Task',         Icon: CheckSquare,  accent: 'text-accent-mint' },
  { to: 'shopping',  label: 'Spesa',        Icon: ShoppingCart, accent: 'text-accent-rose' },
  { to: 'notes',     label: 'Note',         Icon: Note,         accent: 'text-accent-sun' },
  { to: 'reminders', label: 'Promemoria',   Icon: Bell,         accent: 'text-accent-coral' },
];

export function ListHub() {
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'neutral',
      glowAccent: 'mint',
      caption: 'Pronta ad aiutarti con le liste',
      context: 'list',
    });
  }, [setAvatar]);

  return (
    <div className="container-app py-6 space-y-4">
      <h1 className="font-display text-3xl mb-4">Liste</h1>
      <div className="grid grid-cols-2 gap-3">
        {TABS.map(({ to, label, Icon, accent }) => (
          <Link key={to} to={`/list/${to}`} className="block">
            <Card padding="lg" elevation={1} className="hover:shadow-2 transition-shadow">
              <Icon size={32} weight="duotone" className={accent} />
              <CardTitle className="mt-3">{label}</CardTitle>
              <CardSubtitle>0 elementi</CardSubtitle>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
