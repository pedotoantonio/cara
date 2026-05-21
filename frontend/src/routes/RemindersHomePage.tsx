// RemindersHomePage — la home di /reminders.
//
// 4 grandi card colorate (una per categoria) + sotto la strip dei
// prossimi 7 giorni. Niente lista grande di task: il "list manager"
// è una surface secondaria, raggiungibile da ogni card.

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import {
  CATEGORY_META,
  type Reminder,
  type ReminderCategory,
  formatDue,
  listUpcoming,
} from '../api/reminders';
import { Card } from '../design';

const CATEGORIES: ReminderCategory[] = ['family', 'health', 'documents', 'events'];

export function RemindersHomePage() {
  const navigate = useNavigate();
  const [upcoming, setUpcoming] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    listUpcoming(7, 5)
      .then((r) => !cancelled && setUpcoming(r))
      .catch(() => { /* swallow — empty state */ })
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, []);

  return (
    <main className="min-h-dvh bg-bg text-fg px-4 pt-6 pb-24 max-w-2xl mx-auto">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Ricordi</h1>
        <p className="text-fg-muted mt-1">
          Promemoria semplici per la vita di ogni giorno.
        </p>
      </header>

      <section className="grid grid-cols-2 gap-3 mb-8">
        {CATEGORIES.map((c) => {
          const meta = CATEGORY_META[c];
          return (
            <button
              key={c}
              onClick={() => navigate(`/reminders/category/${c}`)}
              className="text-left"
            >
              <Card className="aspect-[5/4] flex flex-col justify-between p-5 hover:shadow-lg transition-shadow active:scale-[0.98]">
                <div className="text-5xl">{meta.emoji}</div>
                <div>
                  <div className="text-xl font-semibold">{meta.label}</div>
                  <div className="text-sm text-fg-muted mt-0.5">{meta.description}</div>
                </div>
              </Card>
            </button>
          );
        })}
      </section>

      <h2 className="text-sm font-semibold uppercase tracking-wider text-fg-muted mb-2">
        Prossimi 7 giorni
      </h2>
      {loading ? (
        <Card className="p-4 mt-3"><span className="text-fg-muted">Caricamento…</span></Card>
      ) : upcoming.length === 0 ? (
        <Card className="p-5 mt-3 text-center">
          <div className="text-3xl mb-2">🌿</div>
          <div className="font-medium">Nessun promemoria nei prossimi 7 giorni</div>
          <div className="text-sm text-fg-muted mt-1">
            Tocca una categoria qui sopra per crearne uno.
          </div>
        </Card>
      ) : (
        <ul className="mt-3 space-y-2">
          {upcoming.map((r) => (
            <li key={r.id}>
              <button
                onClick={() => navigate(`/reminders/list?focus=${r.id}`)}
                className="w-full text-left"
              >
                <UpcomingRow reminder={r} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-6 text-center">
        <button
          onClick={() => navigate('/reminders/list')}
          className="text-sm text-fg-muted hover:text-fg underline"
        >
          Tutti i miei ricordi →
        </button>
      </div>

    </main>
  );
}

function UpcomingRow({ reminder }: { reminder: Reminder }) {
  const meta = CATEGORY_META[reminder.category];
  const due = formatDue(reminder.due_at);
  const toneClass =
    due.tone === 'alert' ? 'text-rose-600 dark:text-rose-400' :
    due.tone === 'today' ? 'text-amber-600 dark:text-amber-400' :
    'text-fg-muted';
  return (
    <Card className="p-3 flex items-center gap-3 hover:shadow-md transition-shadow">
      <div className="text-2xl shrink-0">{meta.emoji}</div>
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{reminder.title}</div>
        <div className={`text-sm ${toneClass} truncate`}>{due.primary}</div>
      </div>
    </Card>
  );
}

export default RemindersHomePage;
