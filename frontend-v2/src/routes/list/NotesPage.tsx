import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import { Plus, Trash, PencilSimple } from '@phosphor-icons/react';
import {
  Skeleton,
  Card,
  CardSubtitle,
  Button,
  useToast,
} from '@/design/components';
import {
  createNote,
  deleteNote,
  listNotes,
  updateNote,
  type Note,
} from '@/api/notes';

export function NotesPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [body, setBody] = useState('');
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const saveTimer = useRef<number | null>(null);

  const notesQ = useQuery({ queryKey: ['notes'], queryFn: listNotes, staleTime: 30_000 });
  const notes = notesQ.data ?? [];

  const newM = useMutation({
    mutationFn: () => createNote({ content: '' }),
    onSuccess: (created) => {
      queryClient.setQueryData<Note[]>(['notes'], (prev) =>
        prev ? [created, ...prev] : [created],
      );
      setSelectedId(created.id);
      setBody('');
    },
    onError: (err) => toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message }),
  });

  const updateM = useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) =>
      updateNote(id, { content }),
    onSuccess: (updated) => {
      queryClient.setQueryData<Note[]>(['notes'], (prev) =>
        prev ? prev.map((n) => (n.id === updated.id ? updated : n)) : prev,
      );
      setSavedAt(new Date());
    },
  });

  const deleteM = useMutation({
    mutationFn: (id: string) => deleteNote(id),
    onSuccess: (_, id) => {
      queryClient.setQueryData<Note[]>(['notes'], (prev) =>
        prev ? prev.filter((n) => n.id !== id) : prev,
      );
      if (selectedId === id) {
        setSelectedId(null);
        setBody('');
      }
    },
  });

  // Auto-save with debounce 800ms
  useEffect(() => {
    if (!selectedId) return;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      const current = notes.find((n) => n.id === selectedId);
      if (current && current.content !== body) {
        updateM.mutate({ id: selectedId, content: body });
      }
    }, 800);
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [body, selectedId]);

  function selectNote(n: Note) {
    setSelectedId(n.id);
    setBody(n.content);
    setSavedAt(null);
  }

  const selected = notes.find((n) => n.id === selectedId);

  return (
    <div className="container-app py-4">
      {!selected ? (
        // List view
        <div className="space-y-3">
          <Button leftIcon={<Plus size={18} />} onClick={() => newM.mutate()} loading={newM.isPending}>
            Nuova nota
          </Button>

          {notesQ.isLoading && (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          )}

          {!notesQ.isLoading && notes.length === 0 && (
            <p className="text-text-muted text-center py-8 text-sm">
              Nessuna nota. Crea la prima qui sopra.
            </p>
          )}

          <ul className="space-y-2">
            <AnimatePresence>
              {notes.map((n) => (
                <motion.li
                  key={n.id}
                  layout
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, x: 60 }}
                >
                  <button onClick={() => selectNote(n)} className="block w-full text-left">
                    <Card padding="base" elevation={1} className="hover:border-accent-sun/40 transition-colors">
                      <p className="font-medium line-clamp-2">
                        {n.content.split('\n')[0] || '(senza titolo)'}
                      </p>
                      <CardSubtitle>
                        {new Date(n.updated_at).toLocaleString('it-IT', {
                          day: '2-digit',
                          month: 'short',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </CardSubtitle>
                    </Card>
                  </button>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        </div>
      ) : (
        // Editor view
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setSelectedId(null);
                setBody('');
              }}
            >
              ← Indietro
            </Button>
            <div className="flex items-center gap-2 text-xs text-text-muted">
              {updateM.isPending ? (
                <span className="flex items-center gap-1">
                  <PencilSimple size={12} /> sto salvando…
                </span>
              ) : savedAt ? (
                <span>Salvato {savedAt.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}</span>
              ) : (
                <span>Modifica per salvare</span>
              )}
            </div>
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<Trash size={14} />}
              onClick={() => deleteM.mutate(selected.id)}
            >
              Elimina
            </Button>
          </div>

          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            autoFocus
            placeholder="Scrivi qui…"
            className="w-full min-h-[60vh] rounded-md border border-border-soft bg-bg-base p-4 text-base leading-relaxed outline-none focus:border-accent-sun focus:ring-2 focus:ring-accent-sun/20"
          />
        </div>
      )}
    </div>
  );
}
