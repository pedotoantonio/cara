/**
 * "Le mie scoperte" — vista cronologica della knowledge base CDA dell'utente.
 * Tutto quello che CARA ha trovato per te (radio, articoli, video, podcast,
 * immagini, documenti) in un unico posto, raggruppato per tipo, ri-attivabile
 * con un tap.
 *
 * Modalità admin: toggle "vedi tutti / solo attivi" + bottoni Disattiva/Riattiva
 * per ogni voce. Audit trail tracciato server-side.
 */

import { useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';

import { listKb, setKbItemActive, type CdaKind, type KbItem } from '../api/cda';
import type { User } from '../api/auth';
import { useCdaPlayer } from '../lib/cdaPlayer';

interface OutletCtx {
  user: User;
}

const FILTERS: Array<{ key: 'all' | CdaKind | 'article_feed'; label: string; emoji: string }> = [
  { key: 'all', label: 'Tutto', emoji: '🌐' },
  { key: 'audio_stream', label: 'Radio', emoji: '📻' },
  { key: 'article', label: 'Articoli', emoji: '📰' },
  { key: 'article_feed', label: 'Fonti news', emoji: '📡' },
  { key: 'video', label: 'Video', emoji: '🎬' },
  { key: 'podcast', label: 'Podcast', emoji: '🎙' },
  { key: 'image', label: 'Immagini', emoji: '🖼' },
  { key: 'document', label: 'Documenti', emoji: '📄' },
];

export function DiscoveriesPage() {
  const { user } = useOutletContext<OutletCtx>();
  const isAdmin = user.is_admin;
  const [filter, setFilter] = useState<typeof FILTERS[number]['key']>('all');
  const [items, setItems] = useState<KbItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [adminMode, setAdminMode] = useState(false);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const cda = useCdaPlayer();

  useEffect(() => {
    setLoading(true);
    listKb({
      content_type: filter === 'all' ? undefined : filter,
      limit: 100,
      include_inactive: isAdmin && adminMode,
      all_users: isAdmin && adminMode,
    })
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [filter, adminMode, isAdmin]);

  function open(it: KbItem) {
    if (it.content_type === 'article_feed') {
      window.open(it.url, '_blank', 'noopener,noreferrer');
      return;
    }
    cda.open({
      kind: it.content_type as CdaKind,
      url: it.url,
      title: it.title,
      source_domain: it.source_domain,
      metadata: it.metadata,
      content_id: it.id,
    });
  }

  async function toggleActive(it: KbItem) {
    setPendingId(it.id);
    try {
      const updated = await setKbItemActive(it.id, !it.is_active);
      setItems((prev) => prev.map((i) => (i.id === it.id ? updated : i)));
    } catch (e) {
      alert(`Errore: ${(e as Error).message}`);
    } finally {
      setPendingId(null);
    }
  }

  return (
    <main className="flex-1 overflow-y-auto bg-slate-900 text-slate-100">
      <div className="max-w-3xl mx-auto p-4 md:p-6 space-y-4">
        <header>
          <h1 className="text-xl font-medium">Le mie scoperte</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Tutto ciò che CARA ha trovato per te. Tap su un elemento per riprodurlo.
          </p>
        </header>

        {isAdmin && (
          <label className="flex items-center gap-2 text-xs text-slate-400 select-none">
            <input
              type="checkbox"
              checked={adminMode}
              onChange={(e) => setAdminMode(e.target.checked)}
              className="accent-emerald-500"
            />
            Admin: vedi tutti gli utenti e gli item disattivati
          </label>
        )}

        <div className="flex flex-wrap gap-2">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={`rounded-full border px-3 py-1.5 text-xs ${
                filter === f.key
                  ? 'bg-emerald-600 border-emerald-500 text-white'
                  : 'bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700'
              }`}
            >
              {f.emoji} {f.label}
            </button>
          ))}
        </div>

        {loading ? (
          <p className="text-sm text-slate-500">Carico…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-slate-500">Niente per ora. Prova a chiedermi qualcosa con la voce o nella chat.</p>
        ) : (
          <ul className="space-y-2">
            {items.map((it) => {
              const dim = !it.is_active;
              return (
                <li
                  key={it.id}
                  className={`rounded-xl border p-3 flex items-start gap-3 ${
                    dim
                      ? 'bg-slate-900/40 border-slate-800 opacity-60'
                      : 'bg-slate-800/60 border-slate-700 hover:bg-slate-700/40'
                  }`}
                >
                  <span className="text-lg shrink-0 mt-0.5">{kindEmoji(it.content_type)}</span>
                  <div
                    className="flex-1 min-w-0 cursor-pointer"
                    onClick={() => open(it)}
                  >
                    <p className="text-sm text-slate-100 truncate">
                      {it.title ?? it.url}
                      {dim && <span className="ml-2 text-[10px] text-rose-400">disattivato</span>}
                    </p>
                    <p className="text-[11px] text-slate-500 truncate">
                      {it.source_domain ?? ''}
                      {it.discovered_via ? ` · ${it.discovered_via}` : ''}
                      {' · '}
                      fiducia {Math.round(it.confidence_score * 100)}%
                      {' · '}
                      ✓ {it.success_count}
                      {it.failure_count > 0 && ` · ✗ ${it.failure_count}`}
                    </p>
                  </div>
                  {isAdmin && adminMode && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void toggleActive(it);
                      }}
                      disabled={pendingId === it.id}
                      className={`shrink-0 text-[11px] rounded px-2 py-1 border ${
                        it.is_active
                          ? 'border-rose-700 text-rose-300 hover:bg-rose-900/40'
                          : 'border-emerald-700 text-emerald-300 hover:bg-emerald-900/40'
                      } disabled:opacity-50`}
                    >
                      {pendingId === it.id ? '…' : it.is_active ? 'Disattiva' : 'Riattiva'}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </main>
  );
}

function kindEmoji(kind: string): string {
  switch (kind) {
    case 'audio_stream':
      return '📻';
    case 'article':
      return '📰';
    case 'article_feed':
      return '📡';
    case 'video':
      return '🎬';
    case 'podcast':
      return '🎙';
    case 'image':
      return '🖼';
    case 'document':
      return '📄';
    default:
      return '📌';
  }
}
