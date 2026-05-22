import { useState, type ReactNode } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  HouseLine,
  ChatCircle,
  ListChecks,
  CalendarBlank,
  User,
} from '@phosphor-icons/react';
import { FloatingAvatar } from '@/components/avatar/FloatingAvatar';
import { AvatarDrawer } from '@/components/avatar/AvatarDrawer';
import { VoicePanel } from '@/components/voice/VoicePanel';
import { useAvatarStore } from '@/state/avatar';
import { cn } from '@/lib/cn';
import type { AccentToken } from '@/design/tokens';

interface NavEntry {
  to: string;
  label: string;
  Icon: typeof HouseLine;
  accent: AccentToken;
}

const NAV: NavEntry[] = [
  { to: '/',     label: 'Casa',  Icon: HouseLine,    accent: 'coral' },
  { to: '/chat', label: 'Chat',  Icon: ChatCircle,   accent: 'lilac' },
  { to: '/list', label: 'Liste', Icon: ListChecks,   accent: 'mint' },
  { to: '/life', label: 'Vita',  Icon: CalendarBlank,accent: 'sky' },
  { to: '/me',   label: 'Tu',    Icon: User,         accent: 'rose' },
];

const ACCENT_BG: Record<AccentToken, string> = {
  coral: 'bg-accent-coral/12 text-accent-coral',
  mint: 'bg-accent-mint/12 text-accent-mint',
  sun: 'bg-accent-sun/20 text-[#8E6800]',
  sky: 'bg-accent-sky/12 text-accent-sky',
  lilac: 'bg-accent-lilac/12 text-accent-lilac',
  rose: 'bg-accent-rose/24 text-[#A53A5E]',
  grass: 'bg-accent-grass/12 text-accent-grass',
  clay: 'bg-accent-clay/12 text-accent-clay',
};

export function AppShell({ children }: { children?: ReactNode }) {
  const location = useLocation();
  const isHome = location.pathname === '/';
  const avatarSize = useAvatarStore((s) => s.size);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="min-h-[100dvh] bg-bg-base flex flex-col">
      {/* Top spacer for safe-area */}
      <div style={{ height: 'env(safe-area-inset-top, 0)' }} aria-hidden />

      <main className="flex-1 pb-[calc(4.5rem+env(safe-area-inset-bottom,0))] lg:pb-0 lg:pl-20">
        <Outlet />
        {children}
      </main>

      {/* Floating avatar — visible in every page EXCEPT home (where hero is shown).
          Tap → drawer (placeholder per ora); long-press → voice immediato. */}
      {!isHome && avatarSize !== 'hero' && (
        <FloatingAvatar
          onTap={() => setDrawerOpen(true)}
          onLongPress={() => setVoiceOpen(true)}
        />
      )}

      <AvatarDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onVoice={() => setVoiceOpen(true)}
      />
      <VoicePanel open={voiceOpen} onClose={() => setVoiceOpen(false)} />

      {/* Bottom nav (mobile) */}
      <nav
        className="fixed bottom-0 inset-x-0 z-20 bg-bg-elevated/95 backdrop-blur border-t border-border-soft lg:hidden"
        style={{ paddingBottom: 'env(safe-area-inset-bottom, 0)' }}
      >
        <ul className="flex justify-around items-stretch h-[4.5rem]">
          {NAV.map(({ to, label, Icon, accent }) => (
            <li key={to} className="flex-1">
              <NavLink
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  cn(
                    'flex flex-col items-center justify-center gap-1 h-full px-2 transition-colors duration-quick',
                    'text-text-muted',
                    isActive && 'text-text-primary',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      className={cn(
                        'inline-flex items-center justify-center w-10 h-10 rounded-md transition-colors duration-base',
                        isActive ? ACCENT_BG[accent] : 'bg-transparent',
                      )}
                    >
                      <Icon size={22} weight={isActive ? 'fill' : 'regular'} />
                    </span>
                    <span className="text-xs font-medium">{label}</span>
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/* Side rail (desktop) */}
      <nav className="hidden lg:flex fixed left-0 inset-y-0 z-20 w-20 bg-bg-elevated border-r border-border-soft flex-col items-center py-6 gap-1">
        <div className="font-display text-2xl mb-6 text-text-primary">C</div>
        {NAV.map(({ to, label, Icon, accent }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              cn(
                'group relative flex flex-col items-center justify-center gap-1 w-16 py-3 rounded-md transition-colors duration-quick',
                'text-text-muted hover:text-text-primary',
                isActive && 'text-text-primary',
              )
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={cn(
                    'inline-flex items-center justify-center w-10 h-10 rounded-md transition-colors duration-base',
                    isActive ? ACCENT_BG[accent] : 'group-hover:bg-bg-surface',
                  )}
                >
                  <Icon size={22} weight={isActive ? 'fill' : 'regular'} />
                </span>
                <span className="text-[10px] font-medium tracking-wide uppercase">{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
