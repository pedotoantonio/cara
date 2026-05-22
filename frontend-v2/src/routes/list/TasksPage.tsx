import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence } from 'framer-motion';
import { Calendar, X } from '@phosphor-icons/react';
import { Skeleton, useToast, Button } from '@/design/components';
import { QuickAddInput } from '@/components/lists/QuickAddInput';
import { ListItemCard } from '@/components/lists/ListItemCard';
import {
  createTask,
  deleteTask,
  listTasks,
  updateTask,
  type Task,
} from '@/api/tasks';

function toLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fromLocalInput(local: string): string | null {
  if (!local) return null;
  return new Date(local).toISOString();
}

export function TasksPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [editDate, setEditDate] = useState<string | null>(null);
  const [pendingDate, setPendingDate] = useState<string | null>(null);

  const tasksQ = useQuery({ queryKey: ['tasks'], queryFn: listTasks, staleTime: 30_000 });

  const addM = useMutation({
    mutationFn: (args: { title: string; due_date: string | null }) =>
      createTask({ title: args.title, due_date: args.due_date }),
    onSuccess: (created) => {
      queryClient.setQueryData<Task[]>(['tasks'], (prev) => (prev ? [created, ...prev] : [created]));
      setPendingDate(null);
    },
    onError: (err) => toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message }),
  });

  const toggleM = useMutation({
    mutationFn: ({ id, done }: { id: string; done: boolean }) => updateTask(id, { done }),
    onMutate: async ({ id, done }) => {
      await queryClient.cancelQueries({ queryKey: ['tasks'] });
      const prev = queryClient.getQueryData<Task[]>(['tasks']);
      queryClient.setQueryData<Task[]>(['tasks'], (p) =>
        p ? p.map((t) => (t.id === id ? { ...t, done } : t)) : p,
      );
      return { prev };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['tasks'], ctx.prev);
      toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message });
    },
  });

  const updateM = useMutation({
    mutationFn: (args: { id: string; title?: string; due_date?: string | null }) =>
      updateTask(args.id, { title: args.title, due_date: args.due_date }),
    onSuccess: (updated) => {
      queryClient.setQueryData<Task[]>(['tasks'], (p) =>
        p ? p.map((t) => (t.id === updated.id ? updated : t)) : p,
      );
    },
    onError: (err) => toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message }),
  });

  const deleteM = useMutation({
    mutationFn: (id: string) => deleteTask(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ['tasks'] });
      const prev = queryClient.getQueryData<Task[]>(['tasks']);
      queryClient.setQueryData<Task[]>(['tasks'], (p) => (p ? p.filter((t) => t.id !== id) : p));
      return { prev };
    },
    onError: (err, _id, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['tasks'], ctx.prev);
      toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message });
    },
  });

  const tasks = tasksQ.data ?? [];
  const open = tasks.filter((t) => !t.done);
  const done = tasks.filter((t) => t.done);

  function startEdit(t: Task) {
    setEditingId(t.id);
    setEditText(t.title);
    setEditDate(t.due_date);
  }
  function commitEdit() {
    if (!editingId) return;
    const t = tasks.find((x) => x.id === editingId);
    if (t) {
      const patch: { id: string; title?: string; due_date?: string | null } = { id: editingId };
      if (editText.trim() && editText.trim() !== t.title) patch.title = editText.trim();
      if (editDate !== t.due_date) patch.due_date = editDate;
      if (Object.keys(patch).length > 1) {
        updateM.mutate(patch);
      }
    }
    setEditingId(null);
    setEditText('');
    setEditDate(null);
  }

  return (
    <div className="container-app py-4 space-y-4">
      <div className="space-y-2">
        <QuickAddInput
          placeholder="Nuova task — premi invio"
          onAdd={async (text) => {
            await addM.mutateAsync({ title: text, due_date: pendingDate });
          }}
          disabled={addM.isPending}
        />
        <div className="flex items-center gap-2 pl-3 text-sm text-text-muted">
          <Calendar size={14} weight="duotone" />
          <input
            type="datetime-local"
            value={pendingDate ? toLocalInput(pendingDate) : ''}
            onChange={(e) => setPendingDate(fromLocalInput(e.target.value))}
            className="bg-transparent border-0 outline-none text-sm text-text-secondary"
          />
          {pendingDate && (
            <button
              type="button"
              onClick={() => setPendingDate(null)}
              className="ml-1 p-1 hover:bg-bg-surface rounded-sm"
              aria-label="Rimuovi scadenza"
            >
              <X size={12} />
            </button>
          )}
          {!pendingDate && (
            <span className="text-xs text-text-muted">scadenza opzionale</span>
          )}
        </div>
      </div>

      {tasksQ.isLoading && (
        <ul className="space-y-2">
          {[1, 2, 3].map((i) => (
            <li key={i}>
              <Skeleton className="h-14 w-full" />
            </li>
          ))}
        </ul>
      )}

      {!tasksQ.isLoading && open.length === 0 && done.length === 0 && (
        <p className="text-text-muted text-center py-8 text-sm">
          Nessuna task. Aggiungine una qui sopra.
        </p>
      )}

      {open.length > 0 && (
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted mb-2 px-1">
            Da fare ({open.length})
          </h2>
          <ul className="space-y-2">
            <AnimatePresence>
              {open.map((t) => (
                <ListItemCard
                  key={t.id}
                  done={t.done}
                  accent="mint"
                  onToggleDone={(next) => toggleM.mutate({ id: t.id, done: next })}
                  onDelete={() => deleteM.mutate(t.id)}
                >
                  {editingId === t.id ? (
                    <div className="space-y-1.5">
                      <input
                        autoFocus
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') commitEdit();
                          if (e.key === 'Escape') {
                            setEditingId(null);
                            setEditText('');
                            setEditDate(null);
                          }
                        }}
                        className="w-full bg-transparent border-b border-accent-coral outline-none text-base"
                      />
                      <div className="flex items-center gap-2 text-xs flex-wrap">
                        <Calendar size={12} weight="duotone" />
                        <input
                          type="datetime-local"
                          value={editDate ? toLocalInput(editDate) : ''}
                          onChange={(e) => setEditDate(fromLocalInput(e.target.value))}
                          className="bg-transparent border-0 outline-none text-text-secondary"
                        />
                        {editDate && (
                          <button
                            type="button"
                            onClick={() => setEditDate(null)}
                            className="p-0.5 hover:bg-bg-surface rounded-sm"
                          >
                            <X size={10} />
                          </button>
                        )}
                        <Button size="sm" variant="primary" onClick={commitEdit}>
                          Salva
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <button onClick={() => startEdit(t)} className="block w-full text-left">
                      <p className="font-medium">{t.title}</p>
                      {t.due_date && (
                        <p className="text-xs text-text-muted mt-0.5">
                          {new Date(t.due_date).toLocaleString('it-IT', {
                            day: '2-digit',
                            month: 'short',
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </p>
                      )}
                    </button>
                  )}
                </ListItemCard>
              ))}
            </AnimatePresence>
          </ul>
        </section>
      )}

      {done.length > 0 && (
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted mb-2 px-1">
            Fatte ({done.length})
          </h2>
          <ul className="space-y-2">
            <AnimatePresence>
              {done.map((t) => (
                <ListItemCard
                  key={t.id}
                  done={t.done}
                  accent="mint"
                  onToggleDone={(next) => toggleM.mutate({ id: t.id, done: next })}
                  onDelete={() => deleteM.mutate(t.id)}
                >
                  <p className="font-medium">{t.title}</p>
                </ListItemCard>
              ))}
            </AnimatePresence>
          </ul>
        </section>
      )}
    </div>
  );
}
