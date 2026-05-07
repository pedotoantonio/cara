// Click handler for any task/event chip on the Wall. Opens a modal:
//   - Tasks: full edit form (title / due / owner / done / wall_visible / delete)
//   - Events: read-only display (we don't write back to Google calendar)
//
// Edits go through `/api/v1/wall/tasks/*` (LAN-only). Read-after-write
// for fresh values; the parent caller is expected to refresh its data
// (we expose `onChanged` so the host page can refetch summary/calendar).

import { useEffect, useState } from 'react';

import {
  deleteTask,
  patchTask,
} from '../../api/wall';
import type { WallItem, WallUser } from '../../api/wall';
import { OwnerChip } from './OwnerChip';

interface Props {
  item: WallItem;
  family: WallUser[];
  onClose: () => void;
  onChanged: () => void;
}

function localDatetimeValue(iso: string | null | undefined): string {
  // <input type="datetime-local"> wants `YYYY-MM-DDTHH:mm` in LOCAL tz.
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

function localDatetimeToIso(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}

export function WallItemDetail({ item, family, onClose, onChanged }: Props) {
  const isTask = item.kind === 'task';
  const [title, setTitle] = useState(item.title);
  const [due, setDue] = useState(localDatetimeValue(item.due_date ?? item.start ?? null));
  const [done, setDone] = useState(Boolean(item.done));
  const [ownerId, setOwnerId] = useState<number | null>(item.owner_id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  async function save() {
    if (!isTask) return;
    setBusy(true);
    setError(null);
    try {
      const patch: Parameters<typeof patchTask>[1] = {
        title: title.trim(),
        done,
      };
      patch.due_date = due ? localDatetimeToIso(due) : null;
      if (ownerId && ownerId !== item.owner_id) {
        patch.owner_id = ownerId;
      }
      await patchTask(String(item.id), patch);
      onChanged();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleDoneQuick() {
    if (!isTask) return;
    setBusy(true);
    try {
      await patchTask(String(item.id), { done: !done });
      setDone(!done);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!isTask) return;
    if (!window.confirm(`Eliminare "${item.title}"?`)) return;
    setBusy(true);
    setError(null);
    try {
      await deleteTask(String(item.id));
      onChanged();
      onClose();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-40 bg-black/55 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-bg rounded-xl max-w-md w-full max-h-[88vh] overflow-y-auto p-5 shadow-2xl space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <span
              className="inline-flex items-center px-2 py-0.5 rounded text-2xs uppercase tracking-wide"
              style={{
                background: isTask ? '#fde68a' : '#ddd6fe',
                color: '#0f172a',
              }}
            >
              {isTask ? 'Task' : 'Evento'}
            </span>
            <OwnerChip user={item.owner} variant="compact" />
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-fg-muted hover:text-fg text-xl leading-none"
            aria-label="Chiudi"
          >
            ×
          </button>
        </header>

        {isTask ? (
          <>
            <label className="block">
              <span className="block text-fg-muted text-xs mb-1">Titolo</span>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full bg-surface2 rounded-md px-3 py-2 text-md"
              />
            </label>
            <label className="block">
              <span className="block text-fg-muted text-xs mb-1">Scadenza</span>
              <input
                type="datetime-local"
                value={due}
                onChange={(e) => setDue(e.target.value)}
                className="w-full bg-surface2 rounded-md px-3 py-2 text-md"
              />
              {due && (
                <button
                  type="button"
                  className="mt-1 text-xs text-fg-muted hover:text-fg"
                  onClick={() => setDue('')}
                >
                  Rimuovi scadenza
                </button>
              )}
            </label>
            <label className="block">
              <span className="block text-fg-muted text-xs mb-1">Assegnato a</span>
              <select
                value={ownerId ?? ''}
                onChange={(e) => setOwnerId(parseInt(e.target.value, 10) || null)}
                className="w-full bg-surface2 rounded-md px-3 py-2 text-md"
              >
                {family
                  .filter((u) => u.wall_visible)
                  .map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.emoji} {u.display_name}
                    </option>
                  ))}
              </select>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={done}
                onChange={(e) => setDone(e.target.checked)}
                className="w-5 h-5"
              />
              <span className="text-fg">Completato</span>
            </label>
          </>
        ) : (
          <>
            <h3
              className="font-display text-fg"
              style={{ fontSize: 'clamp(20px, 2vw, 26px)' }}
            >
              {item.title}
            </h3>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-fg-muted">Inizio</dt>
              <dd>{fmtItalian(item.start)}</dd>
              {item.end && (
                <>
                  <dt className="text-fg-muted">Fine</dt>
                  <dd>{fmtItalian(item.end)}</dd>
                </>
              )}
              <dt className="text-fg-muted">Owner</dt>
              <dd>{item.owner ? item.owner.display_name : 'Famiglia'}</dd>
              {item.all_day && (
                <>
                  <dt className="text-fg-muted">Tipo</dt>
                  <dd>Tutto il giorno</dd>
                </>
              )}
            </dl>
            <p className="text-xs text-fg-muted italic">
              Gli eventi del calendario Google sono in sola lettura sul Wall.
              Modificali da Google Calendar; CARA si sincronizza automaticamente.
            </p>
          </>
        )}

        {error && (
          <p className="text-alert text-sm">⚠ {error}</p>
        )}

        {isTask && (
          <div className="flex flex-wrap gap-2 pt-2">
            <button
              type="button"
              onClick={save}
              disabled={busy || !title.trim()}
              className="rounded-pill bg-accent text-bg px-4 py-2 disabled:opacity-50"
            >
              Salva
            </button>
            <button
              type="button"
              onClick={toggleDoneQuick}
              disabled={busy}
              className="rounded-pill bg-surface2 text-fg-soft px-4 py-2"
            >
              {done ? 'Riapri' : 'Segna fatto'}
            </button>
            <button
              type="button"
              onClick={remove}
              disabled={busy}
              className="rounded-pill text-alert hover:bg-alert/10 px-4 py-2 ml-auto"
            >
              Elimina
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function fmtItalian(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('it-IT', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    hour: '2-digit',
    minute: '2-digit',
  });
}
