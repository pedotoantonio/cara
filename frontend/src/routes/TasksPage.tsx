// TasksPage — elenco task con creazione + modifica inline + scadenza.
// Tap su una task → entra in modifica titolo. Bottone "..." → cambio scadenza
// e elimina via BottomSheet. Checkbox a sinistra → toggle done.
//
// Allineata al design system: avorio/terracotta giorno, notte profondo sera.

import { useEffect, useRef, useState } from 'react';

import {
  Task,
  createTask,
  deleteTask,
  listTasks,
  updateTask,
} from '../api/tasks';
import {
  Badge,
  BottomSheet,
  Button,
  Card,
  Field,
  Icon,
  IconButton,
  Input,
  cn,
  useToast,
} from '../design';
import { onFamilyEventPrefix } from '../lib/familySync';
import {
  ensurePushReady,
  enablePush,
  getCurrentSubscription,
  type PushReady,
} from '../lib/push';
import { useReactions } from '../lib/reactions';

const PUSH_BANNER_DISMISS_KEY = 'cara.push.banner_dismissed';

// ── Helpers ────────────────────────────────────────────────────

function dueBadge(due: string | null, done: boolean):
  | { label: string; tone: 'alert' | 'celebrate' | 'muted' | 'accent' }
  | null {
  if (!due || done) return null;
  const dt = new Date(due);
  const now = new Date();
  const diffMs = dt.getTime() - now.getTime();
  const diffDays = Math.floor(diffMs / 86_400_000);
  const sameDay =
    dt.getFullYear() === now.getFullYear() &&
    dt.getMonth() === now.getMonth() &&
    dt.getDate() === now.getDate();

  if (diffMs < 0) return { label: 'in ritardo', tone: 'alert' };
  if (sameDay)    return { label: 'oggi', tone: 'celebrate' };
  if (diffDays < 1) return { label: 'domani', tone: 'celebrate' };
  if (diffDays < 7) return { label: `tra ${diffDays + 1}g`, tone: 'accent' };
  return {
    label: dt.toLocaleDateString('it-IT', { day: '2-digit', month: 'short' }),
    tone: 'muted',
  };
}

function localToISO(value: string): string | null {
  if (!value) return null;
  const dt = new Date(value);
  return Number.isNaN(dt.getTime()) ? null : dt.toISOString();
}

function isoToLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  // datetime-local needs "yyyy-mm-ddThh:mm" in the user's timezone.
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
         `T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatDueLong(iso: string): string {
  return new Date(iso).toLocaleString('it-IT', {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// ── Component ──────────────────────────────────────────────────

export function TasksPage() {
  const reactions = useReactions();
  const toast = useToast();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [draft, setDraft] = useState('');
  const [draftDue, setDraftDue] = useState('');
  const [hideDone, setHideDone] = useState(false);
  const [adding, setAdding] = useState(false);

  // inline-edit state: which task id is in edit mode (title field), and
  // the buffered title text. Esc cancels, Enter saves.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const editInputRef = useRef<HTMLInputElement | null>(null);

  // sheet state for "...": reschedule + delete.
  const [sheetTask, setSheetTask] = useState<Task | null>(null);
  const [sheetDue, setSheetDue] = useState('');

  // Push notifications enrollment status (banner shown when there are
  // tasks with due_date AND notifications aren't yet granted).
  const [pushStatus, setPushStatus] = useState<PushReady | null>(null);
  const [pushSubscribed, setPushSubscribed] = useState<boolean>(false);
  const [pushBusy, setPushBusy] = useState(false);
  const [pushDismissed, setPushDismissed] = useState<boolean>(() => {
    try { return localStorage.getItem(PUSH_BANNER_DISMISS_KEY) === '1'; }
    catch { return false; }
  });

  useEffect(() => {
    let cancelled = false;
    void Promise.all([ensurePushReady(), getCurrentSubscription()]).then(
      ([ready, sub]) => {
        if (cancelled) return;
        setPushStatus(ready);
        setPushSubscribed(sub !== null);
      },
    );
    return () => { cancelled = true; };
  }, []);

  async function handleEnablePush() {
    if (pushBusy) return;
    setPushBusy(true);
    try {
      const r = await enablePush();
      if (r.ok) {
        toast.push({
          kind: 'celebrate',
          title: 'Notifiche attive',
          body: 'Riceverai un promemoria poco prima delle scadenze.',
        });
        setPushSubscribed(true);
        const ready = await ensurePushReady();
        setPushStatus(ready);
      } else {
        toast.push({
          kind: 'alert',
          title: 'Notifiche non attivate',
          body: r.reason ?? 'Riprova fra un momento.',
        });
      }
    } finally {
      setPushBusy(false);
    }
  }

  function dismissPushBanner() {
    setPushDismissed(true);
    try { localStorage.setItem(PUSH_BANNER_DISMISS_KEY, '1'); } catch {/* */}
  }

  async function refresh() {
    try {
      setTasks(await listTasks(!hideDone));
    } catch (err) {
      console.error(err);
      toast.push({ kind: 'alert', title: 'Non riesco a caricare le task' });
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hideDone]);

  // Re-fetch on any family-sync event whose kind starts with "task."
  // (created/updated/deleted from another browser tab or device).
  useEffect(() => {
    return onFamilyEventPrefix('task.', () => { void refresh(); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hideDone]);

  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  // ── CRUD callbacks ─────────────────────────────────────

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || adding) return;
    setAdding(true);
    const dueISO = localToISO(draftDue);
    setDraft('');
    setDraftDue('');
    try {
      await createTask(text, dueISO);
      const all = await listTasks(!hideDone);
      setTasks(all);
    } catch (err) {
      console.error(err);
      toast.push({ kind: 'alert', title: 'Aggiunta fallita' });
    } finally {
      setAdding(false);
    }
  }

  async function toggle(t: Task) {
    try {
      const updated = await updateTask(t.id, { done: !t.done });
      setTasks(cur => cur.map(x => (x.id === t.id ? updated : x)));
      if (updated.done) {
        reactions.trigger('task_done', { message: `Bravo! "${t.title}"` });
      }
    } catch (err) {
      console.error(err);
      toast.push({ kind: 'alert', title: 'Aggiornamento fallito' });
    }
  }

  function startEdit(t: Task) {
    if (t.done) return; // don't edit completed tasks
    setEditingId(t.id);
    setEditingTitle(t.title);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditingTitle('');
  }

  async function commitEdit() {
    if (!editingId) return;
    const newTitle = editingTitle.trim();
    const original = tasks.find(t => t.id === editingId);
    if (!original) { cancelEdit(); return; }
    if (!newTitle || newTitle === original.title) { cancelEdit(); return; }
    try {
      const updated = await updateTask(editingId, { title: newTitle });
      setTasks(cur => cur.map(x => (x.id === editingId ? updated : x)));
      toast.push({ kind: 'ok', title: 'Modificata' });
    } catch (err) {
      console.error(err);
      toast.push({ kind: 'alert', title: 'Salvataggio fallito' });
    } finally {
      cancelEdit();
    }
  }

  function openSheet(t: Task) {
    setSheetTask(t);
    setSheetDue(isoToLocalInput(t.due_date));
  }

  async function commitDue() {
    if (!sheetTask) return;
    const newDueISO = localToISO(sheetDue);
    try {
      const updated = await updateTask(sheetTask.id, { due_date: newDueISO });
      setTasks(cur => cur.map(x => (x.id === sheetTask.id ? updated : x)));
      toast.push({
        kind: 'ok',
        title: newDueISO ? 'Scadenza aggiornata' : 'Scadenza rimossa',
      });
      setSheetTask(null);
    } catch (err) {
      console.error(err);
      toast.push({ kind: 'alert', title: 'Aggiornamento fallito' });
    }
  }

  async function remove(id: string) {
    try {
      await deleteTask(id);
      setTasks(cur => cur.filter(x => x.id !== id));
      toast.push({ kind: 'ok', title: 'Eliminata' });
    } catch (err) {
      console.error(err);
      toast.push({ kind: 'alert', title: 'Eliminazione fallita' });
    }
  }

  // ── Derived counts ────────────────────────────────────

  const hasDueDates = tasks.some(t => !t.done && t.due_date);
  const showPushBanner =
    !pushDismissed &&
    !pushSubscribed &&
    hasDueDates &&
    pushStatus !== null &&
    pushStatus.supported &&
    pushStatus.configured &&
    pushStatus.permission !== 'denied';

  const pending = tasks.filter(t => !t.done).length;
  const overdue = tasks.filter(
    t => !t.done && t.due_date && new Date(t.due_date).getTime() < Date.now(),
  ).length;
  const todays = tasks.filter(t => {
    if (t.done || !t.due_date) return false;
    const d = new Date(t.due_date);
    const n = new Date();
    return d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate();
  }).length;

  // ── Render ────────────────────────────────────────────

  return (
    <div className="px-5 md:px-8 max-w-3xl mx-auto pb-8">
      <div className="flex items-end justify-between gap-3 mb-5">
        <div>
          <h1 className="font-display text-3xl md:text-4xl text-fg leading-tight">
            Task
          </h1>
          <p className="text-sm text-fg-soft mt-1">
            {pending === 0 ? 'Tutto fatto.' : `${pending} da fare`}
            {todays > 0 && (
              <span className="text-celebrate"> · {todays} oggi</span>
            )}
            {overdue > 0 && (
              <span className="text-alert"> · {overdue} in ritardo</span>
            )}
          </p>
        </div>
        <label className="text-xs text-fg-muted flex items-center gap-2 cursor-pointer shrink-0 select-none">
          <input
            type="checkbox"
            checked={hideDone}
            onChange={e => setHideDone(e.target.checked)}
            className="accent-accent w-4 h-4"
          />
          <span className="hidden sm:inline">Nascondi completate</span>
          <span className="sm:hidden">Nascondi ✓</span>
        </label>
      </div>

      {/* Push notifications banner */}
      {showPushBanner && (
        <Card variant="outline" tint="accent" className="mb-4 !p-4">
          <div className="flex items-start gap-3">
            <span className="text-accent shrink-0 mt-0.5">
              <Icon name="bell" size={20} />
            </span>
            <div className="flex-1 min-w-0">
              <p className="font-medium text-fg leading-snug">
                Vuoi un promemoria sul telefono?
              </p>
              <p className="text-xs text-fg-soft mt-1">
                Cara ti avvisa poco prima della scadenza, anche con il
                browser chiuso. Devi solo confermare le notifiche.
              </p>
              <div className="flex gap-2 mt-3">
                <Button
                  variant="primary"
                  size="sm"
                  iconLeft="bell"
                  onClick={handleEnablePush}
                  loading={pushBusy}
                >
                  Attiva notifiche
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={dismissPushBanner}
                >
                  Non ora
                </Button>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Re-permission hint when blocked */}
      {pushStatus?.permission === 'denied' && hasDueDates && !pushDismissed && (
        <Card variant="outline" tint="alert" className="mb-4 !p-3">
          <p className="text-xs text-fg leading-snug">
            Le notifiche sono bloccate per Cara nel browser. Per riceverle,
            apri le impostazioni del sito e consenti le notifiche.
          </p>
        </Card>
      )}

      {/* New task form */}
      <Card variant="raised" className="mb-5">
        <form onSubmit={add} className="flex flex-col sm:flex-row gap-2">
          <Input
            value={draft}
            onChange={e => setDraft(e.target.value)}
            placeholder="Aggiungi una cosa da fare…"
            maxLength={500}
            className="flex-1"
            iconLeft="plus"
          />
          <input
            type="datetime-local"
            value={draftDue}
            onChange={e => setDraftDue(e.target.value)}
            title="Scadenza (facoltativa)"
            className={cn(
              'h-11 rounded-lg bg-surface1 ring-1 ring-fg/8 px-3 text-fg',
              'focus:outline-none focus:ring-2 focus:ring-accent',
              'sm:w-56',
            )}
          />
          <Button
            type="submit"
            variant="primary"
            disabled={!draft.trim() || adding}
            loading={adding}
          >
            Aggiungi
          </Button>
        </form>
      </Card>

      {/* List */}
      <div className="space-y-1.5">
        {tasks.length === 0 && (
          <Card variant="outline" className="text-center py-10 text-sm text-fg-muted">
            Nessuna task. Aggiungine una qui sopra.
          </Card>
        )}

        {tasks.map(t => {
          const badge = dueBadge(t.due_date, t.done);
          const isEditing = editingId === t.id;
          return (
            <div
              key={t.id}
              className={cn(
                'group rounded-xl px-3 py-2.5 transition-all duration-180',
                'flex items-center gap-3',
                t.done
                  ? 'bg-surface1/60 text-fg-muted'
                  : 'bg-surface1 hover:bg-surface2 ring-1 ring-fg/8',
              )}
            >
              <button
                type="button"
                onClick={() => toggle(t)}
                aria-label={t.done ? 'Riapri task' : 'Completa task'}
                className={cn(
                  'shrink-0 h-6 w-6 rounded-md transition-all duration-180 ease-spring',
                  'flex items-center justify-center',
                  t.done
                    ? 'bg-ok text-ivory'
                    : 'ring-2 ring-fg/25 hover:ring-accent hover:bg-accent/10',
                )}
              >
                {t.done && <Icon name="check" size={14} />}
              </button>

              <div className="flex-1 min-w-0">
                {isEditing ? (
                  <input
                    ref={editInputRef}
                    value={editingTitle}
                    onChange={e => setEditingTitle(e.target.value)}
                    onBlur={commitEdit}
                    onKeyDown={e => {
                      if (e.key === 'Enter') { e.preventDefault(); void commitEdit(); }
                      else if (e.key === 'Escape') cancelEdit();
                    }}
                    maxLength={500}
                    className={cn(
                      'w-full bg-bg ring-1 ring-accent rounded-md px-2 py-1',
                      'text-sm text-fg focus:outline-none focus:ring-2 focus:ring-accent',
                    )}
                  />
                ) : (
                  <button
                    type="button"
                    onClick={() => startEdit(t)}
                    disabled={t.done}
                    className={cn(
                      'block w-full text-left text-sm leading-snug',
                      t.done && 'line-through cursor-default',
                      !t.done && 'cursor-text hover:text-accent-dark',
                    )}
                    title={t.done ? '' : 'Tocca per modificare'}
                  >
                    {t.title}
                  </button>
                )}
                {t.due_date && !isEditing && (
                  <p className="text-2xs text-fg-muted mt-0.5">
                    {formatDueLong(t.due_date)}
                  </p>
                )}
              </div>

              {badge && !isEditing && (
                <Badge tone={badge.tone} size="sm">{badge.label}</Badge>
              )}

              {!isEditing && (
                <IconButton
                  name="calendar"
                  label="Modifica scadenza o elimina"
                  size="sm"
                  variant="plain"
                  onClick={() => openSheet(t)}
                  className="opacity-0 group-hover:opacity-100 md:opacity-0 transition"
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Action sheet — reschedule + delete */}
      <BottomSheet
        open={sheetTask !== null}
        onClose={() => setSheetTask(null)}
        title={sheetTask ? sheetTask.title : ''}
        subtitle="Sposta la scadenza o elimina la task."
      >
        <div className="space-y-4 pb-2">
          <Field label="Scadenza" hint="Lascia vuoto per rimuoverla.">
            <input
              type="datetime-local"
              value={sheetDue}
              onChange={e => setSheetDue(e.target.value)}
              className={cn(
                'w-full h-11 rounded-lg bg-surface1 ring-1 ring-fg/8 px-3 text-fg',
                'focus:outline-none focus:ring-2 focus:ring-accent',
              )}
            />
          </Field>
          <div className="flex gap-2 flex-wrap">
            {[
              { label: 'Stasera 18:00', off: { hour: 18, minute: 0, dayDelta: 0 } },
              { label: 'Domani 9:00', off: { hour: 9, minute: 0, dayDelta: 1 } },
              { label: 'Tra 1 ora', off: null as null | { hour: number; minute: number; dayDelta: number } },
              { label: 'Senza data', off: 'clear' as const },
            ].map(opt => (
              <button
                key={opt.label}
                type="button"
                onClick={() => {
                  if (opt.off === 'clear') { setSheetDue(''); return; }
                  const d = new Date();
                  if (!opt.off) {
                    d.setHours(d.getHours() + 1);
                  } else {
                    d.setDate(d.getDate() + opt.off.dayDelta);
                    d.setHours(opt.off.hour, opt.off.minute, 0, 0);
                  }
                  setSheetDue(isoToLocalInput(d.toISOString()));
                }}
                className="text-xs rounded-pill bg-surface1 hover:bg-accent/12 ring-1 ring-fg/8 px-3 py-1.5 transition-all"
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 flex items-center justify-between gap-3 pt-3 border-t border-fg/8">
          <Button
            variant="alert"
            size="sm"
            iconLeft="trash"
            onClick={async () => {
              if (sheetTask) {
                const id = sheetTask.id;
                setSheetTask(null);
                await remove(id);
              }
            }}
          >
            Elimina
          </Button>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => setSheetTask(null)}>
              Annulla
            </Button>
            <Button variant="primary" size="sm" onClick={commitDue}>
              Salva
            </Button>
          </div>
        </div>
      </BottomSheet>
    </div>
  );
}
