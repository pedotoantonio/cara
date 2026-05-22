import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence } from 'framer-motion';
import { Skeleton, useToast } from '@/design/components';
import { QuickAddInput } from '@/components/lists/QuickAddInput';
import { ListItemCard } from '@/components/lists/ListItemCard';
import {
  createTask,
  deleteTask,
  listTasks,
  updateTask,
  type Task,
} from '@/api/tasks';

export function TasksPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');

  const tasksQ = useQuery({ queryKey: ['tasks'], queryFn: listTasks, staleTime: 30_000 });

  const addM = useMutation({
    mutationFn: (title: string) => createTask({ title }),
    onSuccess: (created) => {
      queryClient.setQueryData<Task[]>(['tasks'], (prev) => (prev ? [created, ...prev] : [created]));
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
    mutationFn: ({ id, title }: { id: string; title: string }) => updateTask(id, { title }),
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
  }
  function commitEdit() {
    if (!editingId) return;
    const t = tasks.find((x) => x.id === editingId);
    if (t && editText.trim() && editText.trim() !== t.title) {
      updateM.mutate({ id: editingId, title: editText.trim() });
    }
    setEditingId(null);
    setEditText('');
  }

  return (
    <div className="container-app py-4 space-y-4">
      <QuickAddInput
        placeholder="Nuova task — premi invio"
        onAdd={async (text) => { await addM.mutateAsync(text); }}
        disabled={addM.isPending}
      />

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
                    <input
                      autoFocus
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      onBlur={commitEdit}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') commitEdit();
                        if (e.key === 'Escape') {
                          setEditingId(null);
                          setEditText('');
                        }
                      }}
                      className="w-full bg-transparent border-b border-accent-coral outline-none text-base"
                    />
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
