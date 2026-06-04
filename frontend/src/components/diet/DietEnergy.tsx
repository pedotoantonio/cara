// DietEnergy — tab "Energia": fabbisogno, introdotte, bruciate, residuo,
// su Giorno/Settimana/Mese/Anno, con grafico per giorno (o per mese
// sull'anno) e lista allenamenti. Aggiornamento in tempo reale: rifetcha
// dopo ogni log pasto/allenamento e quando torni sulla tab.

import { useCallback, useEffect, useState } from 'react';

import {
  PERIOD_LABEL,
  deleteExercise,
  getEnergy,
  listExercise,
  type EnergyPeriod,
  type EnergyStats,
  type ExerciseLog,
} from '../../api/diet';
import { Button, Card, Icon } from '../../design';
import { DietProfileSheet } from './DietProfileSheet';
import { ExerciseLogSheet } from './ExerciseLogSheet';

const PERIODS: EnergyPeriod[] = ['day', 'week', 'month', 'year'];

export function DietEnergy() {
  const [period, setPeriod] = useState<EnergyPeriod>('day');
  const [stats, setStats] = useState<EnergyStats | null>(null);
  const [exercises, setExercises] = useState<ExerciseLog[]>([]);
  const [profileOpen, setProfileOpen] = useState(false);
  const [exerciseOpen, setExerciseOpen] = useState(false);

  const refresh = useCallback(() => {
    getEnergy(period).then(setStats).catch(() => undefined);
    listExercise().then(setExercises).catch(() => undefined);
  }, [period]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Real-time: refetch when the tab/window regains focus.
  useEffect(() => {
    const onFocus = () => refresh();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [refresh]);

  if (!stats) return <div className="text-fg-muted text-sm">Caricamento…</div>;

  return (
    <div className="space-y-4">
      {/* Period selector */}
      <div className="flex gap-1.5 overflow-x-auto no-scrollbar">
        {PERIODS.map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={`shrink-0 rounded-full px-4 h-9 text-sm font-medium transition ${
              period === p ? 'bg-accent text-ivory' : 'bg-surface2 text-fg-muted'
            }`}
          >
            {PERIOD_LABEL[p]}
          </button>
        ))}
      </div>

      {!stats.profile_complete ? (
        <Card tint="accent">
          <p className="text-sm mb-3">
            Completa il profilo (sesso, età, altezza, peso, attività) per calcolare
            il tuo fabbisogno calorico giornaliero.
          </p>
          <Button variant="primary" fullWidth onClick={() => setProfileOpen(true)}>
            Completa il profilo
          </Button>
        </Card>
      ) : (
        <>
          {/* Headline numbers */}
          <div className="grid grid-cols-2 gap-3">
            <Big
              label={period === 'day' ? 'Fabbisogno' : 'Fabbisogno totale'}
              value={stats.target_total}
              tone="text-sky-600 dark:text-sky-300"
              hint={`${stats.daily_target} kcal/giorno`}
            />
            <Big label="Introdotte" value={stats.consumed} tone="text-orange-600 dark:text-orange-300" />
            <Big label="Bruciate (sport)" value={stats.burned} tone="text-emerald-600 dark:text-emerald-300" prefix="−" />
            <Big
              label="Residuo"
              value={stats.remaining}
              tone={stats.remaining != null && stats.remaining < 0 ? 'text-alert' : 'text-violet-600 dark:text-violet-300'}
              hint={stats.remaining != null && stats.remaining < 0 ? 'sopra il fabbisogno' : 'ancora disponibili'}
            />
          </div>

          {/* Formula reminder */}
          <p className="text-2xs text-fg-muted text-center">
            residuo = fabbisogno − introdotte + bruciate · BMR Mifflin-St Jeor × attività
          </p>

          {/* Breakdown chart */}
          <Card>
            <h3 className="font-semibold text-sm mb-3">
              Andamento {period === 'year' ? 'per mese' : 'per giorno'}
            </h3>
            <BreakdownChart stats={stats} />
          </Card>

          {period !== 'day' && (
            <div className="grid grid-cols-2 gap-3 text-center">
              <MiniStat label="media introdotte/g" value={`${stats.avg_consumed_per_day}`} />
              <MiniStat label="media bruciate/g" value={`${stats.avg_burned_per_day}`} />
            </div>
          )}
        </>
      )}

      {/* Exercise today */}
      <Card>
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold text-sm">Allenamenti di oggi</h3>
          <button onClick={() => setExerciseOpen(true)} className="text-accent text-sm flex items-center gap-1">
            <Icon name="plus" size={16} /> Aggiungi
          </button>
        </div>
        {exercises.length === 0 ? (
          <p className="text-fg-muted text-sm">Nessun allenamento registrato oggi.</p>
        ) : (
          <ul className="space-y-2">
            {exercises.map((e) => (
              <li key={e.id} className="flex items-center gap-2 text-sm">
                <span className="flex-1">{e.activity}</span>
                <span className="text-fg-muted">{e.duration_min} min</span>
                <span className="font-semibold text-emerald-600 dark:text-emerald-300">−{e.kcal_burned} kcal</span>
                <button
                  onClick={async () => { await deleteExercise(e.id); refresh(); }}
                  className="text-fg-muted hover:text-alert"
                  aria-label="Elimina"
                >
                  <Icon name="trash" size={16} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <button onClick={() => setProfileOpen(true)} className="text-sm text-fg-muted underline w-full text-center">
        Modifica profilo / obiettivo
      </button>

      <DietProfileSheet open={profileOpen} onClose={() => setProfileOpen(false)} onSaved={() => refresh()} />
      <ExerciseLogSheet open={exerciseOpen} onClose={() => setExerciseOpen(false)} onLogged={() => refresh()} />
    </div>
  );
}

function Big({
  label, value, tone, hint, prefix = '',
}: { label: string; value: number | null; tone: string; hint?: string; prefix?: string }) {
  return (
    <Card className="py-3">
      <div className="text-2xs text-fg-muted">{label}</div>
      <div className={`text-2xl font-bold ${tone}`}>
        {value == null ? '—' : `${prefix}${value}`}
        <span className="text-sm font-normal text-fg-muted"> kcal</span>
      </div>
      {hint && <div className="text-2xs text-fg-muted">{hint}</div>}
    </Card>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="py-2">
      <div className="text-lg font-bold">{value}</div>
      <div className="text-2xs text-fg-muted">{label}</div>
    </Card>
  );
}

function BreakdownChart({ stats }: { stats: EnergyStats }) {
  const max = Math.max(
    1,
    ...stats.breakdown.map((b) => Math.max(b.consumed, b.target ?? 0)),
  );
  return (
    <div className="flex items-end gap-1 h-32">
      {stats.breakdown.map((b, i) => {
        const cH = (b.consumed / max) * 100;
        const tH = b.target ? (b.target / max) * 100 : 0;
        return (
          <div key={i} className="flex-1 flex flex-col items-center justify-end h-full min-w-0">
            <div className="relative w-full flex justify-center items-end h-full">
              {/* target marker line */}
              {b.target ? (
                <span
                  className="absolute left-0 right-0 border-t border-dashed border-sky-400/70"
                  style={{ bottom: `${tH}%` }}
                />
              ) : null}
              {/* consumed bar */}
              <div
                className="w-2/3 rounded-t bg-orange-400/80"
                style={{ height: `${cH}%` }}
                title={`${b.consumed} introdotte${b.burned ? ` · ${b.burned} bruciate` : ''}`}
              />
            </div>
            <span className="text-[9px] text-fg-muted mt-1 truncate w-full text-center">{b.label}</span>
          </div>
        );
      })}
    </div>
  );
}
