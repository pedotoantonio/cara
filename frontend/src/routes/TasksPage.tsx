import { useEffect, useState } from 'react';

import {
  Task,
  createTask,
  deleteTask,
  listTasks,
  updateTask,
} from '../api/tasks';
import { useReactions } from '../lib/reactions';

/** Returns a human-readable badge for a task's due date, or null. */
function dueBadge(due: string | null, done: boolean): { label: string; tone: string } | null {
  if (!due) return null;
  const dt = new Date(due);
  const now = new Date();
  const diffMs = dt.getTime() - now.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (done) return null;

  // Same date check
  const sameDay =
    dt.getFullYear() === now.getFullYear() &&
    dt.getMonth() === now.getMonth() &&
    dt.getDate() === now.getDate();

  if (diffMs < 0) {
    return { label: 'in ritardo', tone: 'bg-rose-500/20 text-rose-300 border-rose-500/40' };
  }
  if (sameDay) {
    return { label: 'oggi', tone: 'bg-amber-500/20 text-amber-300 border-amber-500/40' };
  }
  if (diffDays < 1) {
    return { label: 'domani', tone: 'bg-amber-500/15 text-amber-200 border-amber-500/30' };
  }
  if (diffDays < 7) {
    return {
      label: `tra ${diffDays + 1} g`,
      tone: 'bg-slate-700/40 text-slate-300 border-slate-600/40',
    };
  }
  return {
    label: dt.toLocaleDateString('it-IT', { day: '2-digit', month: 'short' }),
    tone: 'bg-slate-700/30 text-slate-400 border-slate-700/40',
  };
}

/** Convert local "yyyy-mm-ddThh:mm" (datetime-local) to UTC ISO string for the API. */
function localToISO(value: string): string | null {
  if (!value) return null;
  const dt = new Date(value); // browser interprets as local
  if (Number.isNaN(dt.getTime())) return null;
  return dt.toISOString();
}

export function TasksPage() {
  const reactions = useReactions();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [draft, setDraft] = useState('');
  const [draftDue, setDraftDue] = useState('');
  const [hideDone, setHideDone] = useState(false);
  const [adding, setAdding] = useState(false);

  async function refresh() {
    try {
      setTasks(await listTasks(!hideDone));
    } catch (e) {
      console.error(e);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hideDone]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || adding) return;
    setAdding(true);
    const dueISO = localToISO(draftDue);
    setDraft('');
    setDraftDue('');
    try {
      const t = await createTask(text, dueISO);
      // Refresh whole list so server-side ordering applies (due_date asc).
      const all = await listTasks(!hideDone);
      setTasks(all);
      void t;
    } catch (err) {
      console.error(err);
    } finally {
      setAdding(false);
    }
  }

  async function toggle(t: Task) {
    try {
      const updated = await updateTask(t.id, { done: !t.done });
      setTasks((cur) => cur.map((x) => (x.id === t.id ? updated : x)));
      if (updated.done) {
        reactions.trigger('task_done', { message: `Bravo! "${t.title}"` });
      }
    } catch (err) {
      console.error(err);
    }
  }

  async function remove(id: string) {
    try {
      await deleteTask(id);
      setTasks((cur) => cur.filter((x) => x.id !== id));
    } catch (err) {
      console.error(err);
    }
  }

  const pending = tasks.filter((t) => !t.done).length;
  const overdue = tasks.filter(
    (t) => !t.done && t.due_date && new Date(t.due_date).getTime() < Date.now(),
  ).length;

  return (
    <main className="flex-1 flex flex-col">
      <header className="border-b border-slate-800 px-4 md:px-6 py-4 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-medium">Le tue cose da fare</h1>
          <p className="text-xs text-slate-500 mt-0.5 truncate">
            {pending === 0 ? 'tutto fatto 🎉' : `${pending} da fare`}
            {overdue > 0 && <span className="text-rose-400"> · {overdue} in ritardo</span>}
          </p>
        </div>
        <label className="text-xs text-slate-400 flex items-center gap-2 cursor-pointer shrink-0">
          <input
            type="checkbox"
            checked={hideDone}
            onChange={(e) => setHideDone(e.target.checked)}
            className="accent-emerald-500"
          />
          <span className="hidden sm:inline">Nascondi completati</span>
          <span className="sm:hidden">Nascondi ✓</span>
        </label>
      </header>

      <form onSubmit={add} className="border-b border-slate-800 p-3 md:p-4 flex flex-col sm:flex-row gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Aggiungi una cosa da fare…"
          maxLength={500}
          className="flex-1 rounded-xl bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
        />
        <input
          type="datetime-local"
          value={draftDue}
          onChange={(e) => setDraftDue(e.target.value)}
          title="Scadenza (facoltativa)"
          className="rounded-xl bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
        />
        <button
          type="submit"
          disabled={!draft.trim() || adding}
          className="rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-4 py-2 text-sm font-medium"
        >
          Aggiungi
        </button>
      </form>

      <div className="flex-1 overflow-y-auto p-4 space-y-1">
        {tasks.length === 0 && (
          <div className="text-center text-slate-500 text-sm py-12">
            Niente in lista. Aggiungine una qui sopra.
          </div>
        )}
        {tasks.map((t) => {
          const badge = dueBadge(t.due_date, t.done);
          return (
            <div
              key={t.id}
              className={`group flex items-center gap-3 rounded-xl px-3 py-2 ${
                t.done ? 'bg-slate-800/40 text-slate-500' : 'bg-slate-800/60'
              }`}
            >
              <button
                type="button"
                onClick={() => toggle(t)}
                aria-label={t.done ? 'segna come da fare' : 'segna come fatto'}
                className={`w-5 h-5 shrink-0 rounded-md border ${
                  t.done
                    ? 'bg-emerald-500 border-emerald-500 flex items-center justify-center text-white text-xs'
                    : 'border-slate-600 hover:border-emerald-500'
                }`}
              >
                {t.done ? '✓' : ''}
              </button>
              <div className="flex-1 min-w-0">
                <p className={`text-sm truncate ${t.done ? 'line-through' : ''}`}>{t.title}</p>
                {t.due_date && (
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {new Date(t.due_date).toLocaleString('it-IT', {
                      day: '2-digit',
                      month: 'short',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </p>
                )}
              </div>
              {badge && (
                <span
                  className={`text-[11px] px-2 py-0.5 rounded-full border whitespace-nowrap ${badge.tone}`}
                >
                  {badge.label}
                </span>
              )}
              <button
                type="button"
                onClick={() => remove(t.id)}
                className="md:opacity-0 md:group-hover:opacity-100 text-slate-500 hover:text-rose-400 text-xs transition"
                aria-label="elimina"
              >
                ×
              </button>
            </div>
          );
        })}
      </div>
    </main>
  );
}
