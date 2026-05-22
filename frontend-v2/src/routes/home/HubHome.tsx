import { useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { Microphone, ArrowRight, CalendarBlank, Bell, CheckSquare, Sun } from '@phosphor-icons/react';
import { CaraFace } from '@/components/avatar/CaraFace';
import { useAvatarStore } from '@/state/avatar';
import { useAuthStore } from '@/state/auth';
import { Card, CardTitle, CardSubtitle, Badge, Skeleton, Button } from '@/design/components';
import { buildGreeting, timeOfDay } from '@/lib/greeting';
import {
  fetchFamilyResidence,
  fetchWeather,
  listRemindersUpcoming,
  listTasks,
  type TaskItem,
  type ReminderUpcoming,
} from '@/api/home';

interface UpcomingItem {
  kind: 'task' | 'reminder';
  id: string;
  title: string;
  when: string;
  category?: string;
}

function mergeUpcoming(tasks: TaskItem[], reminders: ReminderUpcoming[]): UpcomingItem[] {
  const out: UpcomingItem[] = [];
  for (const t of tasks) {
    if (t.done || !t.due_date) continue;
    out.push({ kind: 'task', id: `t-${t.id}`, title: t.title, when: t.due_date });
  }
  for (const r of reminders) {
    out.push({
      kind: 'reminder',
      id: `r-${r.id}`,
      title: r.title,
      when: r.due_at,
      category: r.category,
    });
  }
  return out
    .filter((x) => new Date(x.when) >= new Date(Date.now() - 60 * 60 * 1000)) // ora-1h in poi
    .sort((a, b) => +new Date(a.when) - +new Date(b.when))
    .slice(0, 3);
}

function fmtWhen(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const isTomorrow = d.toDateString() === tomorrow.toDateString();

  const hm = d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
  if (sameDay) return `oggi · ${hm}`;
  if (isTomorrow) return `domani · ${hm}`;
  return d.toLocaleDateString('it-IT', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function HubHome() {
  const user = useAuthStore((s) => s.user);
  const setAvatar = useAvatarStore((s) => s.setAvatar);

  // Avatar in modalità HERO sulla home
  useEffect(() => {
    setAvatar({
      size: 'hero',
      energy: timeOfDay() === 'night' ? 'sleeping' : 'idle',
      emotion: 'happy',
      posture: 'attentive',
      glowAccent: 'coral',
      caption: null,
      context: 'home',
    });
  }, [setAvatar]);

  const greeting = useMemo(() => buildGreeting(user?.full_name, user?.tone_preference), [user]);

  const tasksQ = useQuery({
    queryKey: ['tasks'],
    queryFn: listTasks,
    staleTime: 30_000,
  });

  const remindersQ = useQuery({
    queryKey: ['reminders.upcoming'],
    queryFn: () => listRemindersUpcoming(7),
    staleTime: 60_000,
  });

  const residenceQ = useQuery({
    queryKey: ['family.residence'],
    queryFn: fetchFamilyResidence,
    staleTime: 5 * 60_000,
  });

  const weatherQ = useQuery({
    queryKey: ['weather.current', residenceQ.data?.lat, residenceQ.data?.lon],
    queryFn: () =>
      residenceQ.data ? fetchWeather(residenceQ.data.lat, residenceQ.data.lon) : null,
    enabled: !!residenceQ.data,
    staleTime: 5 * 60_000,
  });

  const upcoming = useMemo(
    () => mergeUpcoming(tasksQ.data ?? [], remindersQ.data ?? []),
    [tasksQ.data, remindersQ.data],
  );

  return (
    <div className="container-app pt-4 pb-8">
      {/* Topbar minima — meteo + notifiche */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-text-secondary text-sm">
          <Sun size={18} weight="duotone" className="text-accent-sun" />
          {weatherQ.data ? (
            <span>
              {residenceQ.data?.city ?? 'Ferrara'} ·{' '}
              <strong className="text-text-primary">
                {weatherQ.data.temperature != null
                  ? `${Math.round(weatherQ.data.temperature)}°`
                  : '—'}
              </strong>
            </span>
          ) : (
            <Skeleton variant="text" className="w-32" />
          )}
        </div>
        <Link
          to="/me"
          className="text-text-muted hover:text-text-primary"
          aria-label="Profilo"
        >
          <Bell size={20} />
        </Link>
      </div>

      {/* Hero CaraFace + greeting */}
      <motion.section
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.2, 0, 0, 1] }}
        className="flex flex-col items-center text-center my-6"
      >
        <div className="relative">
          <CaraFace size={220} energy="idle" emotion="happy" />
        </div>
        <h1 className="font-display text-3xl mt-4 text-text-primary">{greeting.title}</h1>
        <p className="mt-1 text-text-secondary">{greeting.subtitle}</p>

        {/* Voice CTA */}
        <Button
          size="lg"
          variant="primary"
          leftIcon={<Microphone size={22} weight="fill" />}
          className="mt-5"
          // Voice flow viene cablato in M2 (Capabilities). Per ora apre la chat.
        >
          Parla con me
        </Button>
      </motion.section>

      {/* Prossimi 3 */}
      <section className="mt-6">
        <div className="flex items-center justify-between mb-2 px-1">
          <h2 className="font-semibold text-md text-text-primary flex items-center gap-2">
            <CalendarBlank size={18} weight="duotone" className="text-accent-sky" />
            Prossimi
          </h2>
          <Link to="/life/calendar" className="text-xs text-text-muted hover:text-text-primary">
            tutto ›
          </Link>
        </div>

        {tasksQ.isLoading || remindersQ.isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : upcoming.length === 0 ? (
          <Card padding="lg" surface="surface" elevation={0}>
            <p className="text-text-secondary text-sm text-center">
              Nessun impegno nei prossimi giorni. Goditi un po' di calma.
            </p>
          </Card>
        ) : (
          <ul className="space-y-2">
            {upcoming.map((item) => (
              <li key={item.id}>
                <Card padding="base" elevation={1} className="flex items-center gap-3">
                  <span
                    className={
                      item.kind === 'task'
                        ? 'inline-flex items-center justify-center w-10 h-10 rounded-md bg-accent-mint/12 text-accent-mint'
                        : 'inline-flex items-center justify-center w-10 h-10 rounded-md bg-accent-coral/12 text-accent-coral'
                    }
                  >
                    {item.kind === 'task' ? (
                      <CheckSquare size={20} weight="duotone" />
                    ) : (
                      <Bell size={20} weight="duotone" />
                    )}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{item.title}</p>
                    <p className="text-xs text-text-muted mt-0.5">{fmtWhen(item.when)}</p>
                  </div>
                  {item.category && (
                    <Badge tone="sky" size="sm">
                      {item.category}
                    </Badge>
                  )}
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Suggerimento contestuale (placeholder M5 — proactivity) */}
      <section className="mt-6">
        <Card padding="lg" surface="surface" elevation={0}>
          <CardTitle>Suggerimento</CardTitle>
          <CardSubtitle className="mt-1">
            Ti aspetto qui per fare di più insieme. Le Liste, la Chat e il tuo Profilo sono
            sempre raggiungibili dal menu in basso.
          </CardSubtitle>
          <div className="mt-3 flex gap-2">
            <Link to="/list/tasks">
              <Button size="sm" variant="secondary" rightIcon={<ArrowRight size={14} />}>
                Vai alle task
              </Button>
            </Link>
          </div>
        </Card>
      </section>
    </div>
  );
}
