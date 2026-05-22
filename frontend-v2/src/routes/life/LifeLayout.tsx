import { useEffect } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { CalendarBlank, Newspaper, Sun, MusicNote } from '@phosphor-icons/react';
import { useAvatarStore } from '@/state/avatar';
import { cn } from '@/lib/cn';

const TABS = [
  { to: '/life/calendar', label: 'Calendario', Icon: CalendarBlank, glow: 'sky' },
  { to: '/life/meteo',    label: 'Meteo',      Icon: Sun,           glow: 'sun' },
  { to: '/life/news',     label: 'News',       Icon: Newspaper,     glow: 'clay' },
  { to: '/life/radio',    label: 'Radio',      Icon: MusicNote,     glow: 'clay' },
] as const;

export function LifeLayout() {
  const location = useLocation();
  const setAvatar = useAvatarStore((s) => s.setAvatar);

  useEffect(() => {
    const active = TABS.find((t) => location.pathname.startsWith(t.to));
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'happy',
      glowAccent: (active?.glow ?? 'sky') as 'sky' | 'sun' | 'clay',
      caption: null,
      context: `life:${active?.label ?? '?'}`,
    });
  }, [location.pathname, setAvatar]);

  return (
    <div className="flex flex-col min-h-[calc(100dvh-4.5rem-env(safe-area-inset-bottom,0))]">
      <header className="topbar border-b border-border-soft">
        <h1 className="font-display text-2xl">Vita</h1>
      </header>

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
                      ? 'border-accent-sky text-text-primary'
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
