import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CaretLeft, CaretRight, CheckSquare, Bell, CalendarBlank } from '@phosphor-icons/react';
import { Card, CardSubtitle, Skeleton, Badge } from '@/design/components';
import { cn } from '@/lib/cn';
import { listEvents, mergeForCalendar, type UnifiedCalendarItem } from '@/api/calendar';
import { listTasks } from '@/api/tasks';
import { listUpcomingReminders } from '@/api/reminders';
import { getDayInfo, type DayInfo } from '@/api/calendarInfo';

const MONTH_NAMES = [
  'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno',
  'Luglio', 'Agosto', 'Settembre', 'Ottobre', 'Novembre', 'Dicembre',
];
const DAY_NAMES = ['L', 'M', 'M', 'G', 'V', 'S', 'D'];

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}
function startOfWeek(d: Date): Date {
  const day = d.getDay(); // 0=Sun, 1=Mon
  const offset = day === 0 ? -6 : 1 - day;
  const r = new Date(d);
  r.setDate(d.getDate() + offset);
  r.setHours(0, 0, 0, 0);
  return r;
}

function toIsoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function CalendarPage() {
  const [anchor, setAnchor] = useState<Date>(new Date());
  // Pre-seleziona OGGI così l'utente vede subito le info del giorno
  const [selectedDay, setSelectedDay] = useState<Date | null>(new Date());

  const monthStart = startOfMonth(anchor);
  const gridStart = startOfWeek(monthStart);

  // Info del giorno selezionato (santo, luna, sole, proverbio, ecc.)
  const dayInfoQ = useQuery({
    queryKey: ['calendar', 'day-info', selectedDay ? toIsoDate(selectedDay) : 'none'],
    queryFn: () => getDayInfo(selectedDay ? toIsoDate(selectedDay) : undefined),
    enabled: !!selectedDay,
    staleTime: 60 * 60_000,
  });

  const days: Date[] = useMemo(() => {
    const arr: Date[] = [];
    const cur = new Date(gridStart);
    for (let i = 0; i < 42; i++) {
      arr.push(new Date(cur));
      cur.setDate(cur.getDate() + 1);
    }
    return arr;
  }, [gridStart]);

  // Fetch data for the visible range
  const startISO = days[0]?.toISOString() ?? '';
  const endISO = (days[days.length - 1] ?? new Date()).toISOString();

  const eventsQ = useQuery({
    queryKey: ['events', startISO, endISO],
    queryFn: () => listEvents(startISO, endISO),
    staleTime: 60_000,
  });
  const tasksQ = useQuery({ queryKey: ['tasks'], queryFn: listTasks, staleTime: 30_000 });
  const remsQ = useQuery({
    queryKey: ['reminders.upcoming.month'],
    queryFn: () => listUpcomingReminders(60, 100),
    staleTime: 60_000,
  });

  const allItems = useMemo(
    () => mergeForCalendar(eventsQ.data ?? [], tasksQ.data ?? [], remsQ.data ?? []),
    [eventsQ.data, tasksQ.data, remsQ.data],
  );

  function itemsForDay(d: Date): UnifiedCalendarItem[] {
    const key = d.toDateString();
    return allItems.filter((x) => new Date(x.when).toDateString() === key);
  }

  const today = new Date();
  const todayKey = today.toDateString();
  const selectedKey = selectedDay?.toDateString();

  return (
    <div className="container-app py-4 space-y-4">
      <div className="flex items-center justify-between">
        <button
          onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1))}
          className="p-2 -m-2 rounded-md text-text-secondary hover:bg-bg-surface"
          aria-label="Mese precedente"
        >
          <CaretLeft size={22} />
        </button>
        <h2 className="font-display text-xl">
          {MONTH_NAMES[anchor.getMonth()]} {anchor.getFullYear()}
        </h2>
        <button
          onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1))}
          className="p-2 -m-2 rounded-md text-text-secondary hover:bg-bg-surface"
          aria-label="Mese successivo"
        >
          <CaretRight size={22} />
        </button>
      </div>

      <div className="grid grid-cols-7 gap-px text-xs text-text-muted mb-1">
        {DAY_NAMES.map((d, i) => (
          <div key={i} className="text-center py-1">{d}</div>
        ))}
      </div>

      <div className="grid grid-cols-7 gap-px bg-border-soft rounded-md overflow-hidden">
        {days.map((d, idx) => {
          const inMonth = d.getMonth() === anchor.getMonth();
          const isToday = d.toDateString() === todayKey;
          const isSelected = d.toDateString() === selectedKey;
          const items = itemsForDay(d);
          return (
            <button
              key={idx}
              onClick={() => setSelectedDay(d)}
              className={cn(
                'min-h-[64px] sm:min-h-[80px] bg-bg-base p-1 sm:p-1.5 text-left transition-colors',
                inMonth ? 'text-text-primary' : 'text-text-muted bg-bg-surface',
                isSelected && 'ring-2 ring-accent-coral ring-inset',
              )}
            >
              <div className="flex items-center justify-between">
                <span
                  className={cn(
                    'inline-flex items-center justify-center text-xs font-medium',
                    isToday &&
                      'w-6 h-6 rounded-full bg-accent-coral text-text-inverse',
                  )}
                >
                  {d.getDate()}
                </span>
                {items.length > 0 && (
                  <span className="text-[10px] text-text-muted">{items.length}</span>
                )}
              </div>
              <div className="mt-1 space-y-0.5 hidden sm:block">
                {items.slice(0, 2).map((it) => (
                  <div
                    key={it.id}
                    className={cn(
                      'text-[10px] truncate leading-tight rounded-xs px-1',
                      it.kind === 'task' && 'bg-accent-mint/15 text-accent-mint',
                      it.kind === 'reminder' && 'bg-accent-coral/15 text-accent-coral',
                      it.kind === 'event' && 'bg-accent-sky/15 text-accent-sky',
                    )}
                  >
                    {it.title}
                  </div>
                ))}
                {items.length > 2 && (
                  <div className="text-[10px] text-text-muted">+{items.length - 2}</div>
                )}
              </div>
              {items.length > 0 && (
                <div className="sm:hidden flex gap-0.5 mt-0.5">
                  {items.slice(0, 3).map((it) => (
                    <span
                      key={it.id}
                      className={cn(
                        'inline-block w-1.5 h-1.5 rounded-full',
                        it.kind === 'task' && 'bg-accent-mint',
                        it.kind === 'reminder' && 'bg-accent-coral',
                        it.kind === 'event' && 'bg-accent-sky',
                      )}
                    />
                  ))}
                </div>
              )}
            </button>
          );
        })}
      </div>

      {/* Day info card (santo, luna, sole, proverbio, ecc.) — visibile
          per QUALSIASI giorno selezionato (oggi pre-selezionato by default). */}
      {selectedDay && dayInfoQ.data && (
        <DayInfoBox info={dayInfoQ.data} />
      )}

      {/* Selected day items */}
      {selectedDay && (
        <section className="mt-4">
          <h3 className="font-semibold text-md mb-2">
            Impegni di{' '}
            {selectedDay.toLocaleDateString('it-IT', {
              weekday: 'long',
              day: 'numeric',
              month: 'long',
            })}
          </h3>
          {itemsForDay(selectedDay).length === 0 ? (
            <p className="text-sm text-text-muted">Nessun impegno in questo giorno.</p>
          ) : (
            <ul className="space-y-2">
              {itemsForDay(selectedDay).map((it) => (
                <li key={it.id}>
                  <Card padding="base" elevation={1}>
                    <div className="flex items-center gap-3">
                      {it.kind === 'task' && <CheckSquare size={20} className="text-accent-mint" />}
                      {it.kind === 'reminder' && <Bell size={20} className="text-accent-coral" />}
                      {it.kind === 'event' && <CalendarBlank size={20} className="text-accent-sky" />}
                      <div className="flex-1 min-w-0">
                        <p className="font-medium truncate">{it.title}</p>
                        <CardSubtitle>
                          {new Date(it.when).toLocaleTimeString('it-IT', {
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </CardSubtitle>
                      </div>
                      {it.category && (
                        <Badge tone="sky" size="sm">
                          {it.category}
                        </Badge>
                      )}
                    </div>
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {(eventsQ.isLoading || tasksQ.isLoading || remsQ.isLoading) && (
        <Skeleton className="h-4 w-32" />
      )}
    </div>
  );
}


function DayInfoBox({ info }: { info: DayInfo }) {
  return (
    <section className="mt-3 p-3 sm:p-4 rounded-xl bg-bg-elevated border border-border-soft space-y-2">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-display text-lg text-text-primary capitalize">
          {info.long_format_it}
        </h3>
        <span className="text-xs text-text-muted">
          Settimana {info.week_number} · {info.season}
        </span>
      </header>

      {info.is_holiday && info.holiday_name && (
        <div className="px-2.5 py-1.5 rounded-md bg-accent-coral/10 text-accent-coral text-sm">
          🎉 <strong>{info.holiday_name}</strong>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
        {info.saint && (
          <div className="flex items-start gap-2">
            <span className="text-accent-sun flex-shrink-0">✝️</span>
            <span className="text-text-secondary">
              <span className="text-text-muted text-xs block">Santo del giorno</span>
              {info.saint}
            </span>
          </div>
        )}
        {info.sunrise && info.sunset && (
          <div className="flex items-start gap-2">
            <span className="text-accent-sun flex-shrink-0">☀️</span>
            <span className="text-text-secondary">
              <span className="text-text-muted text-xs block">Sole</span>
              <span className="font-mono">
                {info.sunrise} → {info.sunset}
              </span>
              {info.daylight_hours && (
                <span className="text-text-muted text-xs ml-1">
                  · {info.daylight_hours.toFixed(1)}h
                </span>
              )}
            </span>
          </div>
        )}
        <div className="flex items-start gap-2">
          <span className="text-xl flex-shrink-0">{info.moon_phase_emoji}</span>
          <span className="text-text-secondary capitalize">
            <span className="text-text-muted text-xs block">Luna</span>
            {info.moon_phase} · {Math.round(info.moon_illumination * 100)}%
          </span>
        </div>
        {info.countdowns[0] && (
          <div className="flex items-start gap-2">
            <span className="flex-shrink-0">{info.countdowns[0].emoji}</span>
            <span className="text-text-secondary">
              <span className="text-text-muted text-xs block">Prossimo evento</span>
              {info.countdowns[0].label}{' '}
              <span className="text-text-muted">
                ({info.countdowns[0].days_to === 0
                  ? 'oggi'
                  : info.countdowns[0].days_to === 1
                    ? 'domani'
                    : `fra ${info.countdowns[0].days_to}gg`})
              </span>
            </span>
          </div>
        )}
      </div>

      {info.proverb && (
        <p className="text-xs italic text-text-muted border-l-2 border-border-soft pl-2 mt-2">
          "{info.proverb}"
        </p>
      )}
    </section>
  );
}
