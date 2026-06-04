// New AppShell — bottom nav (5) on mobile, side rail (full) on desktop,
// top bar with greeting + theme toggle + profile sheet.
//
// Visivamente: bg avorio (giorno) / blu notte (sera), niente grigio puro.
// L'identità "una pianta che respira nel salotto" si esprime con:
//   - bordi morbidi (rounded-pill, rounded-2xl)
//   - ombre calde, mai grigie
//   - micro-animazione "rise" all'ingresso pagina
//   - icone custom mai geometriche pure

import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';

import type { User } from '../api/auth';
import { Icon, IconButton, BottomSheet, Badge, useTheme, cn } from '../design';
import type { IconName } from '../design';
import {
  flushQueue,
  isOnline,
  onOnlineChange,
  onQueueChange,
  queueLength,
} from '../lib/offlineQueue';
import { triggerInstall } from './InstallPwaPrompt';
import { RadioMiniBar } from './RadioMiniBar';

function isStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  if (window.matchMedia?.('(display-mode: standalone)').matches) return true;
  return Boolean((window.navigator as { standalone?: boolean }).standalone);
}

interface AppShellProps {
  user: User;
  onLogout: () => void;
  refreshMe: () => void;
}

interface NavEntry {
  to: string;
  label: string;
  icon: IconName;
  end?: boolean;
}

// Primary 5 — sempre visibili in bottom nav e in cima al rail.
const PRIMARY: NavEntry[] = [
  { to: '/',         label: 'Casa',     icon: 'home',     end: true },
  { to: '/wallet',   label: 'Wallet',   icon: 'wallet' },
  { to: '/chat',     label: 'Chat',     icon: 'chat' },
  { to: '/tasks',    label: 'Task',     icon: 'task' },
  { to: '/settings', label: 'Tu',       icon: 'profile' },
];

// Secondary — accessibili da "Altro" su mobile, sempre visibili in rail.
const SECONDARY: NavEntry[] = [
  { to: '/menu',             label: 'Stanze',    icon: 'home' },
  { to: '/diet',             label: 'Nutrizione', icon: 'heart' },
  { to: '/shopping',         label: 'Spesa',     icon: 'shopping' },
  { to: '/notes',            label: 'Note',      icon: 'note' },
  { to: '/news',             label: 'News',      icon: 'news' },
  { to: '/radio',            label: 'Radio',     icon: 'radio' },
  { to: '/me/memory',        label: 'Memoria',   icon: 'spark' },
  { to: '/me/proposte',      label: 'Proposte',  icon: 'bell' },
  { to: '/me/integrazioni',  label: 'Connessi',  icon: 'calendar' },
  { to: '/discoveries',      label: 'Scoperte',  icon: 'sparkle' },
];

const ADMIN_ENTRIES: NavEntry[] = [
  { to: '/admin', label: 'Admin', icon: 'settings' },
];

function greetingFor(now = new Date()): string {
  const h = now.getHours();
  if (h < 6)  return 'È ancora notte';
  if (h < 12) return 'Buongiorno';
  if (h < 18) return 'Buon pomeriggio';
  if (h < 22) return 'Buonasera';
  return 'Buonanotte';
}

function firstName(user: User): string {
  return user.full_name?.split(' ')[0] ?? user.email.split('@')[0];
}

export function AppShell({ user, onLogout, refreshMe: _refreshMe }: AppShellProps) {
  const [moreOpen, setMoreOpen] = useState(false);
  const { resolved: theme, toggle: toggleTheme } = useTheme();
  const location = useLocation();

  // Online/offline + queue size — drives the offline banner.
  const [online, setOnline] = useState<boolean>(isOnline());
  const [queueSize, setQueueSize] = useState<number>(queueLength());
  useEffect(() => {
    const off1 = onOnlineChange(setOnline);
    const off2 = onQueueChange(setQueueSize);
    // On mount, attempt to flush any leftover queue from the last session.
    void flushQueue();
    return () => { off1(); off2(); };
  }, []);

  const allNav = user.is_admin
    ? [...PRIMARY, ...SECONDARY, ...ADMIN_ENTRIES]
    : [...PRIMARY, ...SECONDARY];

  const greeting = greetingFor();
  const name = firstName(user);

  return (
    <div className="flex flex-col md:flex-row h-dvh bg-bg text-fg">
      {/* ── Desktop / tablet rail ───────────────────────────── */}
      <aside
        className={cn(
          'hidden md:flex md:w-20 lg:w-60 shrink-0 flex-col',
          'bg-surface1 border-r border-fg/8',
          'py-5 px-3 lg:px-4',
        )}
      >
        <div className="flex items-center gap-2.5 px-2 mb-6">
          <CaraMark />
          <div className="hidden lg:block">
            <div className="font-display text-lg leading-none">Cara</div>
            <div className="text-2xs text-fg-muted mt-0.5">la casa parla</div>
          </div>
        </div>

        <nav className="flex-1 flex flex-col gap-1 overflow-y-auto">
          <RailGroup title="Principale" items={PRIMARY} />
          <RailGroup title="Altro" items={SECONDARY} />
          {user.is_admin && <RailGroup title="Admin" items={ADMIN_ENTRIES} />}
        </nav>

        <div className="mt-3 pt-3 border-t border-fg/8 flex items-center gap-2 px-1">
          <IconButton
            name={theme === 'night' ? 'sun' : 'moon'}
            label={theme === 'night' ? 'Modalità giorno' : 'Modalità sera'}
            onClick={toggleTheme}
            size="sm"
          />
          <button
            type="button"
            onClick={onLogout}
            className="hidden lg:flex flex-1 items-center gap-2 text-xs text-fg-muted hover:text-alert transition-colors px-2 py-1.5 rounded-pill"
            title={`Esci (${user.email})`}
          >
            <Icon name="close" size={14} />
            <span>Esci</span>
          </button>
        </div>
      </aside>

      {/* ── Main column ─────────────────────────────────────── */}
      <div className="flex-1 min-h-0 flex flex-col">
        <TopBar
          greeting={greeting}
          name={name}
          theme={theme}
          onToggleTheme={toggleTheme}
          unread={0}
          location={location.pathname}
        />

        {(!online || queueSize > 0) && (
          <div
            className={cn(
              'mx-5 md:mx-8 mb-2 rounded-xl px-4 py-2.5 ring-1',
              'flex items-center gap-2.5',
              !online
                ? 'bg-alert/12 ring-alert/30 text-fg'
                : 'bg-celebrate/12 ring-celebrate/30 text-fg',
              'animate-rise',
            )}
            role="status"
          >
            <Icon
              name={!online ? 'close' : 'sparkle'}
              size={16}
              className={!online ? 'text-alert' : 'text-celebrate'}
            />
            <div className="text-sm leading-snug flex-1 min-w-0">
              {!online ? (
                <>
                  <strong>Offline.</strong>{' '}
                  Le modifiche restano sul telefono finché torni online
                  {queueSize > 0 && <> ({queueSize} in attesa)</>}.
                </>
              ) : (
                <>Sincronizzazione… {queueSize} modifiche in coda.</>
              )}
            </div>
          </div>
        )}

        <main
          key={location.pathname}
          className="flex-1 min-h-0 overflow-y-auto pb-20 md:pb-2 animate-rise"
        >
          <Outlet context={{ user }} />
        </main>
      </div>

      {/* Persistent radio mini-bar */}
      <RadioMiniBar />

      {/* ── Mobile bottom nav ───────────────────────────────── */}
      <nav
        className={cn(
          'md:hidden fixed inset-x-0 bottom-0 z-30',
          'bg-bg/85 backdrop-blur-md border-t border-fg/8',
          'pb-[env(safe-area-inset-bottom)]',
        )}
      >
        <div className="flex items-stretch h-16">
          {PRIMARY.map(n => (
            <BottomTab key={n.to} entry={n} />
          ))}
          <button
            type="button"
            onClick={() => setMoreOpen(true)}
            className="flex-1 flex flex-col items-center justify-center gap-0.5 text-fg-muted active:scale-95 transition"
          >
            <Icon name="plus" size={22} />
            <span className="text-2xs">Altro</span>
          </button>
        </div>
      </nav>

      {/* "Altro" sheet — secondary nav on mobile */}
      <BottomSheet
        open={moreOpen}
        onClose={() => setMoreOpen(false)}
        title="Tutto a portata"
        subtitle="Le altre stanze di Cara"
      >
        <div className="grid grid-cols-3 gap-3 pb-2">
          {[...SECONDARY, ...(user.is_admin ? ADMIN_ENTRIES : [])].map(n => (
            <NavLink
              key={n.to}
              to={n.to}
              onClick={() => setMoreOpen(false)}
              className={({ isActive }) => cn(
                'flex flex-col items-center justify-center gap-2 p-4 rounded-xl transition-all',
                'bg-surface1 active:scale-95',
                isActive && 'ring-2 ring-accent bg-accent/10',
              )}
            >
              <span className="text-accent">
                <Icon name={n.icon} size={26} />
              </span>
              <span className="text-xs font-medium">{n.label}</span>
            </NavLink>
          ))}
        </div>

        <div className="mt-6 pt-4 border-t border-fg/8 flex items-center justify-between">
          <button
            type="button"
            onClick={() => { setMoreOpen(false); toggleTheme(); }}
            className="flex items-center gap-2 text-sm text-fg-soft hover:text-fg"
          >
            <Icon name={theme === 'night' ? 'sun' : 'moon'} size={18} />
            {theme === 'night' ? 'Passa al giorno' : 'Passa alla sera'}
          </button>
          <button
            type="button"
            onClick={() => { setMoreOpen(false); onLogout(); }}
            className="text-sm text-alert hover:underline"
          >
            Esci
          </button>
        </div>

        {!isStandalone() && (
          <div className="mt-3 pt-3 border-t border-fg/8">
            <button
              type="button"
              onClick={() => { setMoreOpen(false); void triggerInstall(); }}
              className={cn(
                'w-full flex items-center justify-center gap-2',
                'rounded-xl bg-accent/10 hover:bg-accent/15',
                'text-accent text-sm font-medium py-2.5 transition',
              )}
            >
              <Icon name="spark" size={18} />
              Installa CARA come app
            </button>
          </div>
        )}

        <div className="mt-3 text-center text-2xs text-fg-muted">
          collegata come {user.email}
        </div>
        <div className="mt-1 text-center text-2xs text-fg-muted/70">
          CARA v{__APP_VERSION__}
        </div>
      </BottomSheet>

      {/* Just to silence unused-route navigation when entries match */}
      <Hidden allNav={allNav} />
    </div>
  );
}

// ── Pieces ─────────────────────────────────────────────────────

function RailGroup({ title, items }: { title: string; items: NavEntry[] }) {
  return (
    <div className="mb-4">
      <div className="hidden lg:block text-2xs uppercase tracking-wider text-fg-muted px-3 mb-1.5">
        {title}
      </div>
      <div className="flex flex-col gap-0.5">
        {items.map(n => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) => cn(
              'flex items-center gap-3 rounded-pill transition-all duration-180 ease-spring',
              'px-2.5 py-2 lg:px-3',
              isActive
                ? 'bg-accent text-ivory shadow-warm [data-theme=night]_&:text-night'
                : 'text-fg-soft hover:text-fg hover:bg-surface2',
            )}
            title={n.label}
          >
            <Icon name={n.icon} size={20} />
            <span className="hidden lg:inline text-sm font-medium">{n.label}</span>
          </NavLink>
        ))}
      </div>
    </div>
  );
}

function BottomTab({ entry }: { entry: NavEntry }) {
  return (
    <NavLink
      to={entry.to}
      end={entry.end}
      className={({ isActive }) => cn(
        'flex-1 flex flex-col items-center justify-center gap-0.5 transition-all',
        'active:scale-95',
        isActive ? 'text-accent' : 'text-fg-muted',
      )}
    >
      {({ isActive }) => (
        <>
          <span className={cn(
            'flex h-9 w-12 items-center justify-center rounded-pill transition-all',
            isActive && 'bg-accent/12',
          )}>
            <Icon name={entry.icon} size={22} />
          </span>
          <span className="text-2xs font-medium">{entry.label}</span>
        </>
      )}
    </NavLink>
  );
}

function TopBar({
  greeting, name, theme, onToggleTheme, unread, location: _loc,
}: {
  greeting: string;
  name: string;
  theme: 'day' | 'night';
  onToggleTheme: () => void;
  unread: number;
  location: string;
}) {
  return (
    <header className="px-5 pt-4 pb-3 md:px-8 md:pt-6 md:pb-4 flex items-center gap-3">
      <div className="flex-1 min-w-0">
        <div className="text-xs text-fg-muted">{greeting},</div>
        <div className="font-display text-2xl md:text-3xl text-fg leading-tight truncate">
          {name}
        </div>
      </div>

      <div className="flex items-center gap-1">
        {unread > 0 && (
          <Badge tone="alert" size="sm">{unread}</Badge>
        )}
        <IconButton
          name="bell"
          label="Notifiche"
          variant="plain"
          size="md"
        />
        <IconButton
          name={theme === 'night' ? 'sun' : 'moon'}
          label={theme === 'night' ? 'Modalità giorno' : 'Modalità sera'}
          variant="plain"
          size="md"
          onClick={onToggleTheme}
        />
      </div>
    </header>
  );
}

// ── Cara mark — tiny svg leaf, "una pianta che respira"
function CaraMark({ size = 36 }: { size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="inline-flex items-center justify-center rounded-pill bg-accent/15 text-accent animate-breathe"
      style={{ width: size, height: size }}
    >
      <svg viewBox="0 0 24 24" width={size * 0.62} height={size * 0.62} fill="none">
        <path
          d="M12 21c0-5 4-9 9-10-1 5-4.5 9-9 10Zm0 0c0-5-4-9-9-10 1 5 4.5 9 9 10Zm0-1V8M9 8c1.5 0 3-1 3-3 0 2 1.5 3 3 3"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

// React Router needs all routes to be declared in App.tsx; this is just a
// no-op so TS doesn't complain about an unused variable.
function Hidden({ allNav: _ }: { allNav: NavEntry[] }) {
  return null;
}
