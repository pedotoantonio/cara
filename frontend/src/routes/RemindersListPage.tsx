// RemindersListPage — storico raggruppato per "Oggi / Settimana / Più
// avanti". Tap su un item → modale con azioni (Fatto / Snooze / Elimina).

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import {
  CATEGORY_META,
  type Reminder,
  deleteReminder,
  formatDue,
  listReminders,
  markDone,
  snooze,
} from '../api/reminders';
import { Badge, BottomSheet, Button, Card, useToast } from '../design';

export function RemindersListPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [items, setItems] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [focused, setFocused] = useState<Reminder | null>(null);
  const [includeDone, setIncludeDone] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const r = await listReminders({ includeDone });
      setItems(r);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [includeDone]);

  const groups = groupByTime(items);

  return (
    <main className="min-h-dvh bg-bg text-fg px-4 pt-6 pb-24 max-w-2xl mx-auto">
      <header className="mb-6 flex items-center gap-3">
        <button
          onClick={() => navigate('/reminders')}
          className="text-sm text-fg-muted hover:text-fg"
        >
          ←
        </button>
        <h1 className="text-2xl font-bold flex-1">Tutti i ricordi</h1>
        <label className="text-sm text-fg-muted flex items-center gap-2">
          <input
            type="checkbox"
            checked={includeDone}
            onChange={(e) => setIncludeDone(e.target.checked)}
          />
          fatti
        </label>
      </header>

      {loading ? (
        <p className="text-fg-muted">Caricamento…</p>
      ) : items.length === 0 ? (
        <Card className="p-6 text-center">
          <div className="text-3xl mb-2">🌿</div>
          <div>Nessun ricordo attivo.</div>
          <Button className="mt-4" onClick={() => navigate('/reminders')}>
            Crea il primo
          </Button>
        </Card>
      ) : (
        <div className="space-y-6">
          {groups.map((g) => g.items.length > 0 && (
            <section key={g.label}>
              <h2 className="text-sm font-semibold uppercase tracking-wider text-fg-muted mb-2">
                {g.label}
              </h2>
              <ul className="space-y-2">
                {g.items.map((r) => (
                  <li key={r.id}>
                    <button
                      onClick={() => setFocused(r)}
                      className="w-full text-left"
                    >
                      <Row reminder={r} />
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      <BottomSheet
        open={focused !== null}
        onClose={() => setFocused(null)}
        title={focused?.title}
      >
        {focused && (
          <div className="space-y-3 p-1">
            {focused.notes && (
              <p className="text-sm text-fg-muted">{focused.notes}</p>
            )}
            <p className="text-sm">
              📅 {formatDue(focused.due_at).primary} · {formatDue(focused.due_at).secondary}
            </p>
            {focused.recurrence && (
              <p className="text-xs text-fg-muted">
                Ricorrenza: {focused.recurrence}
              </p>
            )}
            <div className="grid grid-cols-2 gap-2 pt-2">
              <Button
                variant="primary"
                onClick={async () => {
                  await markDone(focused.id);
                  toast.push({ kind: 'ok', title: 'Fatto ✅' });
                  setFocused(null);
                  refresh();
                }}
              >
                ✅ Fatto
              </Button>
              <Button
                variant="surface"
                onClick={async () => {
                  await snooze(focused.id, { durationMinutes: 1440 });
                  toast.push({ kind: 'info', title: 'Posticipato di un giorno' });
                  setFocused(null);
                  refresh();
                }}
              >
                ⏰ Domani
              </Button>
              <Button
                variant="ghost"
                onClick={async () => {
                  await snooze(focused.id, { durationMinutes: 60 });
                  toast.push({ kind: 'info', title: 'Posticipato di 1h' });
                  setFocused(null);
                  refresh();
                }}
              >
                ⏰ +1 ora
              </Button>
              <Button
                variant="alert"
                onClick={async () => {
                  if (!confirm('Eliminare questo promemoria?')) return;
                  await deleteReminder(focused.id);
                  toast.push({ kind: 'info', title: 'Eliminato' });
                  setFocused(null);
                  refresh();
                }}
              >
                🗑️ Elimina
              </Button>
            </div>
          </div>
        )}
      </BottomSheet>
    </main>
  );
}

function Row({ reminder }: { reminder: Reminder }) {
  const meta = CATEGORY_META[reminder.category];
  const due = formatDue(reminder.due_at);
  const toneClass =
    due.tone === 'alert' ? 'text-rose-600 dark:text-rose-400' :
    due.tone === 'today' ? 'text-amber-600 dark:text-amber-400' :
    'text-fg-muted';
  return (
    <Card className="p-3 flex items-center gap-3">
      <div className="text-2xl shrink-0">{meta.emoji}</div>
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{reminder.title}</div>
        <div className={`text-xs ${toneClass} truncate`}>
          {due.primary}{reminder.status === 'done' && ' · fatto'}
        </div>
      </div>
      {reminder.recurrence && (
        <Badge tone="muted" className="shrink-0">↻</Badge>
      )}
    </Card>
  );
}

function groupByTime(items: Reminder[]): { label: string; items: Reminder[] }[] {
  const now = new Date();
  const endOfToday = new Date(now); endOfToday.setHours(23, 59, 59, 999);
  const endOfWeek = new Date(now); endOfWeek.setDate(now.getDate() + 7);

  const groups = {
    overdue: [] as Reminder[],
    today: [] as Reminder[],
    week: [] as Reminder[],
    later: [] as Reminder[],
    done: [] as Reminder[],
  };

  for (const r of items) {
    if (r.status === 'done' || r.status === 'archived') { groups.done.push(r); continue; }
    const d = new Date(r.due_at);
    if (d < now)            groups.overdue.push(r);
    else if (d <= endOfToday) groups.today.push(r);
    else if (d <= endOfWeek)  groups.week.push(r);
    else                      groups.later.push(r);
  }

  return [
    { label: 'In ritardo', items: groups.overdue },
    { label: 'Oggi', items: groups.today },
    { label: 'Questa settimana', items: groups.week },
    { label: 'Più avanti', items: groups.later },
    { label: 'Fatti', items: groups.done },
  ];
}

export default RemindersListPage;
