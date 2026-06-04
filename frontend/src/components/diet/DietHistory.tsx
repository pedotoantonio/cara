// DietHistory — storico dei pasti dei giorni passati, raggruppati per
// giorno. Ogni pasto è cliccabile per modificarlo o eliminarlo (riusa
// MealDetailSheet). I pasti mostrati sono solo quelli dell'utente.

import { useCallback, useEffect, useState } from 'react';

import {
  MEAL_LABEL,
  type History,
  type MealLog,
  getHistory,
} from '../../api/diet';
import { Card, Icon } from '../../design';
import { MealDetailSheet } from './MealDetailSheet';

const WEEKDAYS = ['Dom', 'Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab'];
const MONTHS = [
  'gen', 'feb', 'mar', 'apr', 'mag', 'giu',
  'lug', 'ago', 'set', 'ott', 'nov', 'dic',
];

function formatDay(iso: string): string {
  // iso = "YYYY-MM-DD" (giorno locale dal backend)
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((today.getTime() - date.getTime()) / 86400000);
  if (diff === 0) return 'Oggi';
  if (diff === 1) return 'Ieri';
  return `${WEEKDAYS[date.getDay()]} ${d} ${MONTHS[m - 1]}`;
}

export function DietHistory() {
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<MealLog | null>(null);

  const load = useCallback(() => {
    setError(null);
    getHistory(30)
      .then(setHistory)
      .catch((e) => setError(e instanceof Error ? e.message : 'Errore'));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <Card><p className="text-sm text-fg-muted">Non riesco a caricare lo storico.</p></Card>;
  if (!history) return <Card><p className="text-sm text-fg-muted">Carico lo storico…</p></Card>;
  if (history.days.length === 0) {
    return (
      <Card>
        <p className="text-sm text-fg-muted">
          Nessun pasto registrato negli ultimi 30 giorni.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {history.days.map((day) => (
        <Card key={day.day}>
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold">{formatDay(day.day)}</h2>
            {day.total_kcal != null && (
              <span className="text-sm text-accent font-semibold">{day.total_kcal} kcal</span>
            )}
          </div>
          <ul className="space-y-1">
            {day.meals.map((m) => (
              <li key={m.id}>
                <button
                  onClick={() => setDetail(m)}
                  className="w-full flex items-center gap-3 text-left rounded-xl px-1.5 py-1.5 -mx-1.5 hover:bg-surface1 active:scale-[0.99] transition"
                >
                  <span className="text-2xs font-medium text-fg-muted w-16 shrink-0">
                    {MEAL_LABEL[m.meal_type]}
                  </span>
                  <span className="text-sm truncate flex-1">
                    {m.free_text || (m.parsed_items.map((i) => i.food).join(', ') || '—')}
                  </span>
                  {m.est_kcal != null && (
                    <span className="text-2xs text-fg-muted shrink-0">{m.est_kcal} kcal</span>
                  )}
                  <span className="text-fg-muted shrink-0">
                    <Icon name="settings" size={14} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      ))}

      <MealDetailSheet
        meal={detail}
        onClose={() => setDetail(null)}
        onChanged={load}
      />
    </div>
  );
}
