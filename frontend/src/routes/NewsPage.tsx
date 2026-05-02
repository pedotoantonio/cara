import { useEffect, useState } from 'react';

import {
  NewsDisabledError,
  getNews,
  type NewsCategory,
  type NewsItem,
} from '../api/news';
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
    <main className="flex-1 overflow-y-auto bg-slate-900 text-slate-100">
      <div className="max-w-3xl mx-auto p-4 md:p-6 space-y-4">
        <header className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-medium">News 📰</h1>
            <p className="text-xs text-slate-500 mt-0.5">
              Lette dai principali quotidiani italiani e internazionali.
            </p>
          </div>
          {ttsOk && digest && (
            <button
              type="button"
              onClick={toggleRead}
              className={`shrink-0 rounded-xl px-3 py-2 text-xs font-medium border ${
                reading
                  ? 'bg-rose-500/20 border-rose-500/40 text-rose-200'
                  : 'bg-emerald-500/15 border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/25'
              }`}
            >
              {reading ? '⏹ Stop lettura' : '🔊 Leggimi le news'}
            </button>
          )}
        </header>

        {/* Category chips */}
        <nav className="flex flex-wrap gap-2">
          {CATEGORIES.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setCategory(c.id)}
              className={`rounded-full px-3 py-1.5 text-xs border transition ${
                category === c.id
                  ? 'bg-emerald-600 border-emerald-500 text-white'
                  : 'bg-slate-800 border-slate-700 hover:bg-slate-700 text-slate-300'
              }`}
            >
              {c.label}
            </button>
          ))}
        </nav>

        {error && (
          <div className="rounded-2xl bg-rose-500/10 border border-rose-500/40 p-4 text-sm text-rose-200">
            {error}
          </div>
        )}

        {loading && !items.length && (
          <p className="text-sm text-slate-500">Carico le news…</p>
        )}

        <ul className="space-y-3">
          {items.map((it, i) => (
            <li
              key={`${it.link}-${i}`}
              className="rounded-2xl bg-slate-800/60 border border-slate-700 p-4 space-y-1"
            >
              <a
                href={it.link}
                target="_blank"
                rel="noopener noreferrer"
                className="block text-sm font-medium text-slate-100 hover:text-emerald-300"
              >
                {it.title}
              </a>
              {it.summary && (
                <p className="text-xs text-slate-400 line-clamp-2">{it.summary}</p>
              )}
              <p className="text-[11px] text-slate-500">
                {it.source}
                {it.published && <> · {timeAgo(it.published)}</>}
              </p>
            </li>
          ))}
        </ul>

        {!loading && !error && items.length === 0 && (
          <p className="text-sm text-slate-500">Nessuna news disponibile per questa categoria.</p>
        )}
      </div>
    </main>
  );
}
