import { useEffect, useState } from 'react';

import {
  NewsDisabledError,
  getNews,
  type NewsCategory,
  type NewsItem,
} from '../api/news';
import { CategoryHeader } from '../design';
import { isSpeaking, speak, stopSpeaking, ttsAvailable } from '../lib/speech';

const CATEGORIES: { id: NewsCategory; label: string }[] = [
  { id: 'all', label: 'Tutte' },
  { id: 'italia', label: 'Italia' },
  { id: 'mondo', label: 'Mondo' },
  { id: 'economia', label: 'Economia' },
  { id: 'tech', label: 'Tech' },
  { id: 'sport', label: 'Sport' },
];

function timeAgo(iso: string | null): string {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const dm = Math.floor((Date.now() - t) / 60000);
  if (dm < 1) return 'ora';
  if (dm < 60) return `${dm} min fa`;
  const dh = Math.floor(dm / 60);
  if (dh < 24) return `${dh} h fa`;
  const dd = Math.floor(dh / 24);
  return `${dd} g fa`;
}

export function NewsPage() {
  const [category, setCategory] = useState<NewsCategory>('all');
  const [items, setItems] = useState<NewsItem[]>([]);
  const [digest, setDigest] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const ttsOk = ttsAvailable();

  useEffect(() => () => stopSpeaking(), []);

  function toggleRead() {
    if (reading || isSpeaking()) {
      stopSpeaking();
      setReading(false);
      return;
    }
    if (!digest) return;
    setReading(true);
    speak(digest, {
      lang: 'it',
      onEnd: () => setReading(false),
    });
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    stopSpeaking();
    setReading(false);
    getNews(category, 30)
      .then((r) => {
        if (!cancelled) {
          setItems(r.items);
          setDigest(r.digest);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof NewsDisabledError) {
          setError(
            'Le news sono disattivate. Un admin deve abilitare "news_enabled" nelle impostazioni admin.',
          );
        } else {
          setError((e as Error).message);
        }
        setItems([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [category]);

  return (
    <main className="flex-1 overflow-y-auto bg-bg">
      <div className="max-w-3xl mx-auto px-5 md:px-8 py-5 md:py-6 space-y-5">
        <CategoryHeader
          icon="news"
          title="Notizie"
          subtitle="Dai principali quotidiani italiani e internazionali."
          tint="plum"
          pill={`${items.length} ${items.length === 1 ? 'articolo' : 'articoli'}`}
          right={ttsOk && digest ? (
            <button
              type="button"
              onClick={toggleRead}
              className={`shrink-0 rounded-pill px-4 py-2 text-sm font-medium transition shadow-sm ${
                reading
                  ? 'bg-alert text-white hover:bg-alert/90'
                  : 'bg-bg/80 text-fg backdrop-blur-sm ring-1 ring-fg/8 hover:bg-bg'
              }`}
            >
              {reading ? '⏹ Stop' : '🔊 Leggimi'}
            </button>
          ) : undefined}
        />

        {/* Category chips */}
        <nav className="flex flex-wrap gap-2" aria-label="Categoria news">
          {CATEGORIES.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setCategory(c.id)}
              className={`rounded-pill px-4 py-2 text-sm font-medium transition shadow-sm ${
                category === c.id
                  ? 'bg-accent text-white scale-[1.02]'
                  : 'bg-surface1 text-fg-soft hover:bg-surface2 ring-1 ring-fg/8'
              }`}
            >
              {c.label}
            </button>
          ))}
        </nav>

        {error && (
          <div className="rounded-2xl bg-alert/10 ring-1 ring-alert/30 p-4 text-sm text-alert">
            {error}
          </div>
        )}

        {loading && !items.length && (
          <p className="text-sm text-fg-muted text-center py-8">Carico le notizie…</p>
        )}

        <ul className="space-y-3">
          {items.map((it, i) => (
            <li
              key={`${it.link}-${i}`}
              className="rounded-2xl bg-surface1 ring-1 ring-fg/8 p-4 md:p-5 space-y-2 hover:shadow-md hover:ring-fg/15 transition-all duration-200"
            >
              <a
                href={it.link}
                target="_blank"
                rel="noopener noreferrer"
                className="block font-display text-fg hover:text-accent leading-snug"
                style={{ fontSize: 'clamp(15px, 1.5vw, 18px)' }}
              >
                {it.title}
              </a>
              {it.summary && (
                <p className="text-sm text-fg-soft line-clamp-2 leading-relaxed">{it.summary}</p>
              )}
              <p className="text-xs text-fg-muted flex items-center gap-1.5">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-accent/70" aria-hidden />
                <span className="font-medium">{it.source}</span>
                {it.published && <span>· {timeAgo(it.published)}</span>}
              </p>
            </li>
          ))}
        </ul>

        {!loading && !error && items.length === 0 && (
          <p className="text-sm text-fg-muted text-center py-8 rounded-2xl bg-surface1 ring-1 ring-fg/6">
            Nessuna notizia per questa categoria.
          </p>
        )}
      </div>
    </main>
  );
}
