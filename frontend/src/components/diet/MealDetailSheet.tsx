// MealDetailSheet — dettaglio di un pasto registrato, con azioni:
// sposta in un altro slot (colazione/spuntino/pranzo/cena), riscrivi il
// testo (ri-analizzato dal parser), elimina.

import { useEffect, useState } from 'react';

import {
  MEAL_LABEL,
  type MealLog,
  type MealType,
  deleteMeal,
  updateMeal,
} from '../../api/diet';
import { Badge, BottomSheet, Button } from '../../design';

const MEALS: MealType[] = ['colazione', 'spuntino', 'pranzo', 'cena'];

interface Props {
  meal: MealLog | null;
  onClose: () => void;
  onChanged: () => void;
}

export function MealDetailSheet({ meal, onClose, onChanged }: Props) {
  const [text, setText] = useState('');
  const [slot, setSlot] = useState<MealType>('pranzo');
  const [busy, setBusy] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (meal) {
      setText(meal.free_text ?? '');
      setSlot(meal.meal_type);
      setConfirmDel(false);
      setError(null);
    }
  }, [meal]);

  if (!meal) return null;

  const dirty = text.trim() !== (meal.free_text ?? '').trim() || slot !== meal.meal_type;

  async function save() {
    if (!meal) return;
    setBusy(true);
    setError(null);
    try {
      const patch: { meal_type?: MealType; free_text?: string } = {};
      if (slot !== meal.meal_type) patch.meal_type = slot;
      if (text.trim() !== (meal.free_text ?? '').trim()) patch.free_text = text.trim();
      await updateMeal(meal.id, patch);
      onChanged();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Errore salvataggio');
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!meal) return;
    setBusy(true);
    setError(null);
    try {
      await deleteMeal(meal.id);
      onChanged();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Errore eliminazione');
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet
      open={!!meal}
      onClose={onClose}
      title="Pasto registrato"
      subtitle={meal.est_kcal != null ? `≈ ${meal.est_kcal} kcal` : undefined}
    >
      <div className="space-y-4">
        {/* Item riconosciuti */}
        {meal.parsed_items.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {meal.parsed_items.map((it, i) => (
              <Badge key={i} tone={it.protein_category ? 'accent' : 'neutral'}>
                {it.food}
                {it.portion_g ? ` · ${it.portion_g}g` : ''}
              </Badge>
            ))}
          </div>
        )}

        {/* Testo modificabile */}
        <div>
          <label className="mb-1 block text-sm text-fg-muted">Cosa hai mangiato</label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={2}
            className="w-full rounded-2xl bg-surface1 px-4 py-3 text-base ring-1 ring-fg/10 focus:outline-none focus:ring-accent/40 resize-none"
          />
        </div>

        {/* Slot */}
        <div>
          <label className="mb-1 block text-sm text-fg-muted">Pasto</label>
          <div className="flex gap-1.5 overflow-x-auto no-scrollbar">
            {MEALS.map((m) => (
              <button
                key={m}
                onClick={() => setSlot(m)}
                className={`shrink-0 rounded-full px-3 h-8 text-sm transition ${
                  slot === m ? 'bg-accent text-ivory' : 'bg-surface2 text-fg-muted'
                }`}
              >
                {MEAL_LABEL[m]}
              </button>
            ))}
          </div>
        </div>

        {error && <p className="text-sm text-alert">{error}</p>}

        {/* Azioni */}
        {confirmDel ? (
          <div className="rounded-2xl bg-alert/10 ring-1 ring-alert/20 px-3 py-3 space-y-2">
            <p className="text-sm text-alert">Eliminare questo pasto?</p>
            <div className="flex gap-2">
              <Button variant="ghost" fullWidth onClick={() => setConfirmDel(false)} disabled={busy}>
                Annulla
              </Button>
              <Button variant="alert" fullWidth loading={busy} onClick={remove}>
                Elimina
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex gap-2">
            <Button
              variant="ghost"
              iconLeft="trash"
              onClick={() => setConfirmDel(true)}
              disabled={busy}
            >
              Elimina
            </Button>
            <Button
              variant="primary"
              fullWidth
              loading={busy}
              disabled={!dirty || busy}
              onClick={save}
            >
              Salva
            </Button>
          </div>
        )}
      </div>
    </BottomSheet>
  );
}
