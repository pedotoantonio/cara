// DietToday — il widget "Oggi": timeline dei 5 pasti (fatto/manca),
// contatori acqua e caffè, frutta, e il suggerimento per il prossimo
// pasto. Bottone per loggare un pasto.

import { useCallback, useEffect, useState } from 'react';

import {
  MEAL_LABEL,
  addCoffee,
  addWater,
  getEnergy,
  getSuggest,
  getToday,
  type EnergyStats,
  type MealType,
  type Suggest,
  type Today,
} from '../../api/diet';
import { Button, Card, Icon } from '../../design';
import { BarcodeScanner } from './BarcodeScanner';
import { DishIdeas } from './DishIdeas';
import { MealLogSheet } from './MealLogSheet';

function CalCell({
  label, value, tone, prefix = '',
}: { label: string; value: number | null; tone: string; prefix?: string }) {
  return (
    <div>
      <div className={`text-base font-bold ${tone}`}>{value == null ? '—' : `${prefix}${value}`}</div>
      <div className="text-[10px] text-fg-muted">{label}</div>
    </div>
  );
}

function currentMeal(): MealType {
  const h = new Date().getHours();
  if (h < 10) return 'colazione';
  if (h < 12) return 'spuntino';
  if (h < 15) return 'pranzo';
  if (h < 18) return 'spuntino';
  return 'cena';
}

export function DietToday() {
  const [today, setToday] = useState<Today | null>(null);
  const [suggest, setSuggest] = useState<Suggest | null>(null);
  const [energy, setEnergy] = useState<EnergyStats | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [scanOpen, setScanOpen] = useState(false);
  const meal = currentMeal();

  const refresh = useCallback(() => {
    getToday().then(setToday).catch(() => undefined);
    getEnergy('day').then(setEnergy).catch(() => undefined);
    getSuggest(meal === 'colazione' || meal === 'spuntino' ? 'pranzo' : meal)
      .then(setSuggest)
      .catch(() => undefined);
  }, [meal]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function water() {
    const i = await addWater(250);
    setToday((t) => (t ? { ...t, water_ml: i.water_ml } : t));
  }
  async function coffee() {
    const i = await addCoffee(1);
    setToday((t) => (t ? { ...t, coffee_count: i.coffee_count } : t));
  }

  if (!today) return <div className="text-fg-muted text-sm">Caricamento…</div>;

  const waterPct = Math.min(100, (today.water_ml / today.water_target_max) * 100);

  return (
    <div className="space-y-4">
      {/* Timeline 5 pasti */}
      <Card>
        <h2 className="font-semibold mb-3">I pasti di oggi</h2>
        <ul className="space-y-2">
          {today.slots.map((s) => (
            <li key={s.meal_type} className="flex items-center gap-3">
              <span
                className={`h-6 w-6 rounded-full grid place-items-center text-xs ${
                  s.done ? 'bg-ok/20 text-ok' : 'bg-surface2 text-fg-muted'
                }`}
              >
                {s.done ? <Icon name="check" size={14} /> : '·'}
              </span>
              <span className={s.done ? 'font-medium' : 'text-fg-muted'}>
                {MEAL_LABEL[s.meal_type]}
              </span>
              {s.done && s.logs[0]?.free_text && (
                <span className="text-fg-muted text-sm truncate ml-1">
                  — {s.logs[0].free_text}
                </span>
              )}
              {!s.done && <span className="ml-auto text-xs text-fg-muted">manca</span>}
            </li>
          ))}
        </ul>
      </Card>

      {/* Contatori acqua / caffè / frutta */}
      <div className="grid grid-cols-3 gap-3">
        <Card className="text-center">
          <div className="text-2xl font-bold text-sky-500">
            {(today.water_ml / 1000).toFixed(1)}L
          </div>
          <div className="text-2xs text-fg-muted mb-2">
            obiettivo {(today.water_target_min / 1000).toFixed(1)}–
            {(today.water_target_max / 1000).toFixed(1)}L
          </div>
          <div className="h-1.5 rounded-full bg-surface2 overflow-hidden mb-2">
            <div className="h-full bg-sky-400" style={{ width: `${waterPct}%` }} />
          </div>
          <Button size="sm" variant="ghost" fullWidth onClick={water}>
            +250 ml
          </Button>
        </Card>

        <Card className="text-center">
          <div className="text-2xl font-bold text-amber-700 dark:text-amber-300">
            {today.coffee_count}
          </div>
          <div className="text-2xs text-fg-muted mb-2">max {today.coffee_max}/giorno</div>
          <div
            className={`text-xs mb-2 ${
              today.coffee_count > today.coffee_max ? 'text-alert' : 'text-fg-muted'
            }`}
          >
            ☕ caffè
          </div>
          <Button size="sm" variant="ghost" fullWidth onClick={coffee}>
            +1
          </Button>
        </Card>

        <Card className="text-center">
          <div className="text-2xl font-bold text-rose-500">{today.fruit_servings}</div>
          <div className="text-2xs text-fg-muted mb-2">
            obiettivo {today.fruit_target_min}-3/giorno
          </div>
          <div className="text-xs text-fg-muted">🍎 frutta</div>
        </Card>
      </div>

      {/* Bilancio calorico di oggi (tempo reale) */}
      {energy && energy.profile_complete && (
        <Card>
          <div className="flex items-center justify-between mb-2">
            <h2 className="font-semibold text-sm">Bilancio calorico di oggi</h2>
            <span className="text-2xs text-fg-muted">obiettivo {energy.daily_target} kcal</span>
          </div>
          <div className="grid grid-cols-4 gap-2 text-center">
            <CalCell label="introdotte" value={energy.consumed} tone="text-orange-600 dark:text-orange-300" />
            <CalCell label="bruciate" value={energy.burned} tone="text-emerald-600 dark:text-emerald-300" prefix="−" />
            <CalCell label="fabbisogno" value={energy.target_total} tone="text-sky-600 dark:text-sky-300" />
            <CalCell
              label="residuo"
              value={energy.remaining}
              tone={energy.remaining != null && energy.remaining < 0 ? 'text-alert' : 'text-violet-600 dark:text-violet-300'}
            />
          </div>
        </Card>
      )}

      {/* Suggerimento prossimo pasto */}
      {suggest && suggest.suggestions.length > 0 && (
        <Card tint="accent">
          <div className="flex items-center gap-2 mb-1.5">
            <Icon name="spark" size={18} />
            <h2 className="font-semibold">Per {MEAL_LABEL[suggest.meal_type]}</h2>
          </div>
          <p className="text-sm">{suggest.suggestions[0].title}</p>
          {suggest.warnings.length > 0 && (
            <p className="text-xs text-amber-700 dark:text-amber-300 mt-2">
              ⚠️ {suggest.warnings[0]}
            </p>
          )}
          {suggest.context_reminders[0] && (
            <p className="text-xs text-fg-muted mt-1">{suggest.context_reminders[0]}</p>
          )}
        </Card>
      )}

      {/* Cosa cucino? — piatti dagli ingredienti in lista spesa */}
      <DishIdeas meal={meal === 'colazione' || meal === 'spuntino' ? 'pranzo' : meal} />

      <div className="flex gap-2">
        <Button
          variant="primary"
          size="lg"
          fullWidth
          iconLeft="plus"
          onClick={() => setSheetOpen(true)}
        >
          Logga un pasto
        </Button>
        <Button
          variant="surface"
          size="lg"
          iconLeft="scan"
          onClick={() => setScanOpen(true)}
        >
          Scansiona
        </Button>
      </div>

      <MealLogSheet
        open={sheetOpen}
        defaultMeal={meal}
        onClose={() => setSheetOpen(false)}
        onLogged={() => refresh()}
      />

      <BarcodeScanner
        open={scanOpen}
        defaultMeal={meal}
        onClose={() => setScanOpen(false)}
        onLogged={() => refresh()}
      />
    </div>
  );
}
