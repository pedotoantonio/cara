// Menu — family-friendly grid landing as an alternative to the
// voice-first HomePage. One big colored tile per "room" of CARA, plus
// a couple of at-a-glance widgets (today's task progress + family
// presence). Designed to be tappable by elders and kids alike: tiles
// are at least 148px tall, icons are 32px, copy stays short.

import { useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router-dom';

import type { User } from '../api/auth';
import { listTasks, type Task } from '../api/tasks';
import { CaraFace } from '../components/CaraFace';
import { CategoryCard, ProgressRing, type CategoryTint } from '../design';
import type { IconName } from '../design';

interface Room {
  to: string;
  icon: IconName;
  title: string;
  subtitleFn?: () => string | null;
  tint: CategoryTint;
  adminOnly?: boolean;
}

function MenuPageInner({ user }: { user: User }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void listTasks(true).then((t) => {
      if (cancelled) return;
      setTasks(t);
      setLoaded(true);
    }).catch(() => { if (!cancelled) setLoaded(true); });
    return () => { cancelled = true; };
  }, []);

  const { todoCount, doneCount, progress } = useMemo(() => {
    const todo = tasks.filter((t) => !t.done).length;
    const done = tasks.filter((t) => t.done).length;
    const total = todo + done;
    return {
      todoCount: todo,
      doneCount: done,
      progress: total === 0 ? 0 : done / total,
    };
  }, [tasks]);

  const rooms: Room[] = [
    { to: '/tasks',    icon: 'task',     title: 'Cose da fare', subtitleFn: () => todoCount === 0 ? 'Tutto fatto' : `${todoCount} aperte`, tint: 'ocean' },
    { to: '/shopping', icon: 'shopping', title: 'Lista spesa',  subtitleFn: () => 'Cosa serve oggi',  tint: 'terracotta' },
    { to: '/notes',    icon: 'note',     title: 'Note',         subtitleFn: () => 'I tuoi appunti',   tint: 'amber' },
    { to: '/wallet',   icon: 'wallet',   title: 'Wallet',       subtitleFn: () => 'Bolletta, budget', tint: 'sage' },
    { to: '/news',     icon: 'news',     title: 'Notizie',      subtitleFn: () => 'Cosa succede',     tint: 'plum' },
    { to: '/memory',   icon: 'spark',    title: 'Memoria',      subtitleFn: () => 'Cosa Cara ricorda',tint: 'mint' },
    { to: '/integrations', icon: 'sparkle', title: 'Integrazioni', subtitleFn: () => 'Calendar, Gmail',  tint: 'coral' },
    { to: '/chat',     icon: 'chat',     title: 'Chat',         subtitleFn: () => 'Scrivi a Cara',    tint: 'rose' },
    { to: '/admin',    icon: 'settings', title: 'Admin',        subtitleFn: () => 'Solo per te',      tint: 'gold', adminOnly: true },
  ];

  const visibleRooms = rooms.filter((r) => !r.adminOnly || user.is_admin);

  const firstName = user.full_name?.split(' ')[0] || 'famiglia';

  return (
    <div className="px-5 md:px-8 max-w-5xl mx-auto pb-8 select-none">
      {/* Hero — CaraFace inside a soft circle, big friendly greeting */}
      <section className="text-center pt-4 md:pt-8 pb-6">
        <div className="relative inline-block mb-4">
          {/* Concentric circles "halo" behind the face — pure CSS */}
          <span
            aria-hidden="true"
            className="absolute inset-0 -m-6 rounded-full bg-sky-100/70 dark:bg-sky-500/15"
          />
          <span
            aria-hidden="true"
            className="absolute inset-0 -m-3 rounded-full bg-sky-200/60 dark:bg-sky-400/15"
          />
          <span className="relative inline-flex items-center justify-center w-24 h-24 rounded-full bg-white dark:bg-slate-800 shadow-md">
            <CaraFace size={86} energy="idle" emotion="happy" />
          </span>
        </div>
        <h1
          className="font-display text-fg leading-tight"
          style={{ fontSize: 'clamp(28px, 4.8vw, 44px)' }}
        >
          Ciao {firstName}!
        </h1>
        <p className="text-fg-soft mt-1" style={{ fontSize: 'clamp(13px, 1.4vw, 16px)' }}>
          {loaded
            ? doneCount === 0 && todoCount === 0
              ? 'Niente in lista oggi. Goditi la giornata.'
              : `Oggi hai fatto ${doneCount} cose su ${doneCount + todoCount}.`
            : 'Carico la tua giornata…'}
        </p>
        {loaded && doneCount + todoCount > 0 && (
          <div className="inline-flex items-center gap-3 mt-4 px-4 py-2 rounded-pill bg-white dark:bg-slate-800 shadow-sm ring-1 ring-fg/8">
            <ProgressRing
              value={progress}
              size={36}
              thickness={4}
              fillColor="var(--cara-accent, #F97C42)"
            />
            <span className="text-sm font-medium text-fg">
              {Math.round(progress * 100)}% completato
            </span>
          </div>
        )}
      </section>

      {/* Section heading */}
      <h2 className="font-display text-fg text-center mb-4 leading-tight"
          style={{ fontSize: 'clamp(20px, 2.2vw, 26px)' }}>
        Cosa vuoi fare?
      </h2>

      {/* Rooms grid — solid colored tiles. 2 cols on phone, 3 on tablet, 4 on desktop */}
      <section className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 md:gap-4">
        {visibleRooms.map((r) => (
          <CategoryCard
            key={r.to}
            to={r.to}
            icon={r.icon}
            title={r.title}
            subtitle={r.subtitleFn?.()}
            tint={r.tint}
            variant="solid"
          />
        ))}
      </section>
    </div>
  );
}

export function MenuPage() {
  const ctx = useOutletContext<{ user: User }>();
  return <MenuPageInner user={ctx.user} />;
}
