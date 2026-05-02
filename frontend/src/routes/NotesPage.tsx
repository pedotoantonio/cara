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
    <main className="flex-1 flex bg-slate-900">
      {/* List */}
      <aside className="w-56 md:w-64 shrink-0 border-r border-slate-800 flex flex-col">
        <div className="p-3 border-b border-slate-800">
          <button
            type="button"
            onClick={newNote}
            className="w-full rounded-xl bg-emerald-600 hover:bg-emerald-500 px-3 py-2 text-sm font-medium"
          >
            + Nuova nota
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {notes.map((n) => (
            <div
              key={n.id}
              onClick={() => selectNote(n)}
              className={`group flex items-start gap-2 rounded-lg px-3 py-2 cursor-pointer ${
                activeId === n.id
                  ? 'bg-slate-800 text-slate-50'
                  : 'hover:bg-slate-800/60 text-slate-300'
              }`}
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{n.title || 'Senza titolo'}</p>
                <p className="text-xs text-slate-500 truncate">
                  {n.body.slice(0, 60) || 'vuota'}
                </p>
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  remove(n.id);
                }}
                className="md:opacity-0 md:group-hover:opacity-100 text-slate-500 hover:text-rose-400 text-xs"
                aria-label="elimina"
              >
                ×
              </button>
            </div>
          ))}
          {notes.length === 0 && (
            <p className="text-xs text-slate-500 px-3 py-2">Nessuna nota</p>
          )}
        </div>
      </aside>

      {/* Editor */}
      <section className="flex-1 min-w-0 flex flex-col">
        {activeId === null ? (
          <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
            Crea o seleziona una nota.
          </div>
        ) : (
          <>
            <header className="border-b border-slate-800 px-4 md:px-6 py-3 flex items-center gap-3">
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Titolo…"
                maxLength={200}
                className="flex-1 bg-transparent text-lg font-medium focus:outline-none"
              />
              <span className="text-[11px] text-slate-500 shrink-0">
                {savedAt ? `salvata ${savedAt.toLocaleTimeString('it-IT')}` : 'modifica…'}
              </span>
            </header>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Scrivi qui la tua nota…"
              maxLength={20000}
              className="flex-1 bg-transparent p-4 md:p-6 text-sm text-slate-200 resize-none focus:outline-none leading-relaxed"
            />
          </>
        )}
      </section>
    </main>
  );
}
