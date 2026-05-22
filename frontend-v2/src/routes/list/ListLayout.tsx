import { useEffect } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { CheckSquare, ShoppingCart, Note, Bell } from '@phosphor-icons/react';
import { useAvatarStore } from '@/state/avatar';
import { cn } from '@/lib/cn';

const TABS = [
  { to: '/list/tasks', label: 'Task', Icon: CheckSquare, accent: 'accent-mint' },
  { to: '/list/shopping', label: 'Spesa', Icon: ShoppingCart, accent: 'accent-rose' },
  { to: '/list/notes', label: 'Note', Icon: Note, accent: 'accent-sun' },
  { to: '/list/reminders', label: 'Promemoria', Icon: Bell, accent: 'accent-coral' },
];

export function ListLayout() {
  const location = useLocation();
  const setAvatar = useAvatarStore((s) => s.setAvatar);

  useEffect(() => {
    // Avatar glow color matches the active tab
    const active = TABS.find((t) => location.pathname.startsWith(t.to));
    const glowMap = {
      'accent-mint': 'mint',
      'accent-rose': 'rose',
      'accent-sun': 'sun',
      'accent-coral': 'coral',
    } as const;
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'neutral',
      glowAccent: active ? glowMap[active.accent as keyof typeof glowMap] : 'mint',
      caption: null,
      context: `list:${active?.label ?? '?'}`,
    });
  }, [location.pathname, setAvatar]);

  return (
    <div className="flex flex-col min-h-[calc(100dvh-4.5rem-env(safe-area-inset-bottom,0))]">
      <header className="topbar border-b border-border-soft">
        <h1 className="font-display text-2xl">Liste</h1>
      </header>

      {/* Tabs */}
      <nav className="sticky top-[calc(env(safe-area-inset-top,0)+3.5rem)] z-10 bg-bg-base border-b border-border-soft">
        <ul className="container-app flex overflow-x-auto no-scrollbar">
          {TABS.map(({ to, label, Icon }) => (
            <li key={to} className="flex-1 min-w-[80px]">
              <NavLink
                to={to}
                className={({ isActive }) =>
                  cn(
                    'flex flex-col items-center gap-1 py-3 text-sm font-medium border-b-2 transition-colors',
                    isActive
                      ? 'border-accent-coral text-text-primary'
                      : 'border-transparent text-text-muted hover:text-text-primary',
                  )
                }
              >
                <Icon size={18} weight="duotone" />
                {label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="flex-1">
        <Outlet />
      </div>
    </div>
  );
}
