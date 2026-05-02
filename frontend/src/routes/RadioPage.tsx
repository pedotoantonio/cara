import { useEffect, useState } from 'react';

import { listStations, RadioDisabledError, type RadioStation } from '../api/radio';
import { useRadioPlayer } from '../lib/radioPlayer';

const GENRE_LABEL: Record<string, string> = {
  news: 'Notizie',
  talk: 'Cultura',
  music: 'Musica',
  sport: 'Sport',
};

export function RadioPage() {
  const player = useRadioPlayer();
  const [stations, setStations] = useState<RadioStation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listStations()
      .then(setStations)
      .catch((e) => {
        if (e instanceof RadioDisabledError) {
          setError(
            'La radio è disattivata. Un admin deve abilitare "radio_enabled" nelle impostazioni admin.',
          );
        } else {
          setError((e as Error).message);
        }
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="flex-1 overflow-y-auto bg-slate-900 text-slate-100">
      <div className="max-w-3xl mx-auto p-4 md:p-6 space-y-4">
        <header>
          <h1 className="text-xl font-medium">Radio 📻</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Stream pubblici riprodotti direttamente dal tuo browser.
          </p>
        </header>

        {error && (
          <div className="rounded-2xl bg-rose-500/10 border border-rose-500/40 p-4 text-sm text-rose-200">
            {error}
          </div>
        )}

        {loading && <p className="text-sm text-slate-500">Carico le stazioni…</p>}

        <ul className="space-y-2">
          {stations.map((s) => {
            const isCurrent = player.current?.id === s.id;
            return (
              <li
                key={s.id}
                className={`rounded-2xl border p-3 flex items-center gap-3 ${
                  isCurrent
                    ? 'bg-emerald-500/10 border-emerald-500/40'
                    : 'bg-slate-800/60 border-slate-700'
                }`}
              >
                <button
                  type="button"
                  onClick={() => (isCurrent && player.playing ? player.stop() : player.playStation(s))}
                  className={`w-12 h-12 shrink-0 rounded-full text-xl flex items-center justify-center ${
                    isCurrent && player.playing
                      ? 'bg-emerald-500 text-slate-900'
                      : 'bg-slate-700 hover:bg-slate-600 text-slate-100'
                  }`}
                  aria-label={isCurrent && player.playing ? 'pausa' : 'play'}
                >
                  {isCurrent && player.playing ? '⏸' : '▶'}
                </button>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{s.name}</p>
                  <p className="text-xs text-slate-500 truncate">{s.description}</p>
                </div>
                <span className="text-[11px] text-slate-400 shrink-0">
                  {GENRE_LABEL[s.genre] ?? s.genre} · {s.country}
                </span>
              </li>
            );
          })}
        </ul>

        {!loading && !error && stations.length === 0 && (
          <p className="text-sm text-slate-500">Nessuna stazione disponibile.</p>
        )}
      </div>
    </main>
  );
}
