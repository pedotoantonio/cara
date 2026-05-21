import { useEffect, useState } from 'react';

import {
  Note,
  createNote,
  deleteNote,
  listNotes,
  updateNote,
} from '../api/notes';

/** Tiny debounce: returns a stable function that schedules `fn` after `ms` of idleness. */
function debounce<T extends (...a: never[]) => void>(fn: T, ms: number) {
  let h: ReturnType<typeof setTimeout> | null = null;
  return (...args: Parameters<T>) => {
    if (h) clearTimeout(h);
    h = setTimeout(() => fn(...args), ms);
  };
}

export function NotesPage() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [savedAt, setSavedAt] = useState<Date | null>(null);

  async function refresh() {
    try {
      const ns = await listNotes();
      setNotes(ns);
      if (ns.length && !activeId) selectNote(ns[0]);
    } catch (e) {
      console.error(e);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function selectNote(n: Note) {
    setActiveId(n.id);
    setTitle(n.title);
    setBody(n.body);
    setSavedAt(null);
  }

  async function newNote() {
    const n = await createNote('', '');
    setNotes((cur) => [n, ...cur]);
    selectNote(n);
  }

  async function remove(id: string) {
    try {
      await deleteNote(id);
      setNotes((cur) => cur.filter((x) => x.id !== id));
      if (activeId === id) {
        setActiveId(null);
        setTitle('');
        setBody('');
      }
    } catch (e) {
      console.error(e);
    }
  }

  // Debounced auto-save (1.5s of idleness).
  useEffect(() => {
    if (!activeId) return;
    const save = debounce(async (t: string, b: string) => {
      try {
        const updated = await updateNote(activeId, { title: t, body: b });
        setNotes((cur) =>
          [updated, ...cur.filter((x) => x.id !== activeId)].sort(
            (a, b2) => +new Date(b2.updated_at) - +new Date(a.updated_at),
          ),
        );
        setSavedAt(new Date());
      } catch (e) {
        console.error(e);
      }
    }, 1500);
    save(title, body);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, body, activeId]);

  return (
    <main className="flex-1 flex bg-bg">
      {/* List */}
      <aside className="w-60 md:w-72 shrink-0 border-r border-fg/8 flex flex-col bg-surface1/40">
        <div className="p-3 border-b border-fg/8">
          <button
            type="button"
            onClick={newNote}
            className="w-full rounded-2xl bg-accent hover:bg-accent-dark text-white px-4 py-2.5 text-sm font-medium transition shadow-sm hover:shadow-md flex items-center justify-center gap-2"
          >
            <span className="text-base leading-none">+</span> Nuova nota
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {notes.map((n) => (
            <div
              key={n.id}
              onClick={() => selectNote(n)}
              className={`group flex items-start gap-2 rounded-2xl px-3 py-2.5 cursor-pointer transition-all duration-150 ${
                activeId === n.id
                  ? 'bg-surface2 ring-1 ring-accent/30 shadow-sm'
                  : 'hover:bg-surface1 ring-1 ring-transparent hover:ring-fg/8'
              }`}
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate text-fg">{n.title || 'Senza titolo'}</p>
                <p className="text-xs text-fg-muted truncate">
                  {n.body.slice(0, 60) || 'vuota'}
                </p>
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  if (window.confirm(`Eliminare "${n.title || 'questa nota'}"?`)) {
                    void remove(n.id);
                  }
                }}
                className="md:opacity-0 md:group-hover:opacity-100 opacity-60 hover:opacity-100 text-alert p-1 transition"
                aria-label={`Elimina ${n.title || 'nota'}`}
                title="Elimina"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6h14z" />
                  <line x1="10" y1="11" x2="10" y2="17" />
                  <line x1="14" y1="11" x2="14" y2="17" />
                </svg>
              </button>
            </div>
          ))}
          {notes.length === 0 && (
            <p className="text-xs text-fg-muted px-3 py-2 text-center">Nessuna nota.</p>
          )}
        </div>
      </aside>

      {/* Editor */}
      <section className="flex-1 min-w-0 flex flex-col">
        {activeId === null ? (
          <div className="flex-1 flex flex-col items-center justify-center text-fg-muted text-sm gap-2 px-6">
            <div className="w-16 h-16 rounded-2xl bg-surface2 flex items-center justify-center text-fg-muted/60 mb-2">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M5 4h11l4 4v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z" />
                <path d="M8 12h8M8 16h5" />
              </svg>
            </div>
            <p className="font-medium text-fg">Nessuna nota selezionata</p>
            <p>Crea o seleziona una nota dalla lista a sinistra.</p>
          </div>
        ) : (
          <>
            <header className="border-b border-fg/8 px-5 md:px-8 py-4 flex items-center gap-3 bg-surface1/30">
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Titolo…"
                maxLength={200}
                className="flex-1 bg-transparent text-xl font-display font-medium text-fg placeholder:text-fg-muted/50 focus:outline-none"
              />
              <span className="text-xs text-fg-muted shrink-0">
                {savedAt ? `salvata ${savedAt.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}` : 'modifica…'}
              </span>
            </header>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Scrivi qui la tua nota…"
              maxLength={20000}
              className="flex-1 bg-transparent p-5 md:p-8 text-sm text-fg resize-none focus:outline-none leading-relaxed placeholder:text-fg-muted/50"
            />
          </>
        )}
      </section>
    </main>
  );
}
