import { NavLink, Outlet } from 'react-router-dom';

import type { User } from '../api/auth';
import { RadioMiniBar } from './RadioMiniBar';

interface AppShellProps {
  user: User;
  onLogout: () => void;
  refreshMe: () => void;
}

const NAV = [
  { to: '/', label: 'Casa', icon: '🏠', end: true },
  { to: '/chat', label: 'Chat', icon: '💬' },
  { to: '/tasks', label: 'Todo', icon: '✅' },
  { to: '/shopping', label: 'Spesa', icon: '🛒' },
  { to: '/notes', label: 'Note', icon: '📝' },
  { to: '/news', label: 'News', icon: '📰' },
  { to: '/radio', label: 'Radio', icon: '📻' },
  { to: '/discoveries', label: 'Scoperte', icon: '🌐' },
  { to: '/settings', label: 'Impost.', icon: '⚙️' },
];

export function AppShell({ user, onLogout, refreshMe }: AppShellProps) {
  return (
    <div className="flex flex-col md:flex-row h-dvh bg-slate-900 text-slate-100">
      {/* Desktop / tablet rail (left). Hidden on mobile. */}
      <aside className="hidden md:flex w-16 shrink-0 border-r border-slate-800 flex-col items-center py-3">
        <div className="text-xs font-light tracking-tight mb-3 text-slate-400">cara</div>
        <nav className="flex-1 flex flex-col gap-2">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `w-10 h-10 flex items-center justify-center rounded-xl text-lg transition ${
                  isActive
                    ? 'bg-emerald-600/20 ring-1 ring-emerald-500/40'
                    : 'hover:bg-slate-800'
                }`
              }
              title={n.label}
            >
              {n.icon}
            </NavLink>
          ))}
        </nav>
        <button
          type="button"
          onClick={onLogout}
          title={`Esci (${user.email})`}
          className="w-10 h-10 flex items-center justify-center rounded-xl text-rose-400 hover:bg-slate-800 text-lg"
        >
          ⏻
        </button>
      </aside>

      {/* Page outlet — flex-1 to fill remaining vertical/horizontal space */}
      <div className="flex-1 min-h-0 flex flex-col">
        <Outlet context={{ user, refreshMe }} />
      </div>

      {/* Persistent radio mini-bar (only visible when a station is loaded) */}
      <RadioMiniBar />

      {/* Mobile bottom nav. Visible only on small screens. Honors safe-area-inset-bottom. */}
      <nav
        className="md:hidden border-t border-slate-800 bg-slate-900 flex items-stretch
                   pb-[env(safe-area-inset-bottom)]"
      >
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              `flex-1 flex flex-col items-center justify-center py-2 text-[11px] gap-0.5 ${
                isActive ? 'text-emerald-400' : 'text-slate-400'
              }`
            }
          >
            <span className="text-xl leading-none">{n.icon}</span>
            <span>{n.label}</span>
          </NavLink>
        ))}
        <button
          type="button"
          onClick={onLogout}
          aria-label="Esci"
          className="flex-1 flex flex-col items-center justify-center py-2 text-[11px] gap-0.5 text-rose-400"
        >
          <span className="text-xl leading-none">⏻</span>
          <span>Esci</span>
        </button>
      </nav>
    </div>
  );
}
