/**
 * "Le mie scoperte" — vista cronologica della knowledge base CDA dell'utente.
 * Tutto quello che CARA ha trovato per te (radio, articoli, video, podcast,
 * immagini, documenti) in un unico posto, raggruppato per tipo, ri-attivabile
 * con un tap.
 */

import { useEffect, useState } from 'react';

import { listKb, type CdaKind, type KbItem } from '../api/cda';
import { useCdaPlayer } from '../lib/cdaPlayer';

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
  const [filter, setFilter] = useState<typeof FILTERS[number]['key']>('all');
  const [items, setItems] = useState<KbItem[]>([]);
  const [loading, setLoading] = useState(true);
  const cda = useCdaPlayer();

  useEffect(() => {
    setLoading(true);
    listKb({
      content_type: filter === 'all' ? undefined : filter,
      limit: 100,
    })
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [filter]);

  function open(it: KbItem) {
    if (it.content_type === 'article_feed') {
      // A news source. Open the first article from the feed by re-discovering
      // — easier: just open the feed URL in a new tab as a fallback.
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

  return (
    <main className="flex-1 overflow-y-auto bg-slate-900 text-slate-100">
      <div className="max-w-3xl mx-auto p-4 md:p-6 space-y-4">
        <header>
          <h1 className="text-xl font-medium">Le mie scoperte</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Tutto ciò che CARA ha trovato per te. Tap su un elemento per riprodurlo.
          </p>
        </header>

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
            {items.map((it) => (
              <li
                key={it.id}
                className="rounded-xl bg-slate-800/60 border border-slate-700 p-3
                           hover:bg-slate-700/40 cursor-pointer flex items-start gap-3"
                onClick={() => open(it)}
              >
                <span className="text-lg shrink-0">
                  {kindEmoji(it.content_type)}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-slate-100 truncate">
                    {it.title ?? it.url}
                  </p>
                  <p className="text-[11px] text-slate-500 truncate">
                    {it.source_domain ?? ''}
                    {it.discovered_via ? ` · ${it.discovered_via}` : ''}
                    {' · '}
                    fiducia {Math.round(it.confidence_score * 100)}%
                    {' · '}
                    riprodotto {it.success_count} volte
                  </p>
                </div>
              </li>
            ))}
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
