// IntakeSheet — popup per aggiungere acqua o caffè con i dettagli.
// Si apre toccando l'immagine/contatore in DietToday. Per l'acqua offre
// quantità rapide (bicchiere/bottiglia) + campo ml libero; per il caffè
// un selettore quantità. Permette anche di correggere in negativo.

import { useEffect, useState } from 'react';

import { addCoffee, addWater } from '../../api/diet';
import { BottomSheet, Button } from '../../design';

type Kind = 'water' | 'coffee';

interface Props {
  kind: Kind | null;
  current: number;            // ml se water, tazze se coffee
  onClose: () => void;
  onChanged: () => void;
}

// Quantità rapide d'acqua (ml) con etichetta concreta.
const WATER_QUICK = [
  { ml: 150, label: 'Bicchiere', emoji: '🥛' },
  { ml: 250, label: 'Tazza', emoji: '☕' },
  { ml: 500, label: 'Bottiglietta', emoji: '💧' },
  { ml: 1000, label: 'Bottiglia', emoji: '🍶' },
];

export function IntakeSheet({ kind, current, onClose, onChanged }: Props) {
  const [customMl, setCustomMl] = useState('');
  const [coffeeQty, setCoffeeQty] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (kind) {
      setCustomMl('');
      setCoffeeQty(1);
      setError(null);
    }
  }, [kind]);

  async function addW(ml: number) {
    setBusy(true);
    setError(null);
    try {
      await addWater(ml);
      onChanged();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Errore');
    } finally {
      setBusy(false);
    }
  }

  async function addC(count: number) {
    setBusy(true);
    setError(null);
    try {
      await addCoffee(count);
      onChanged();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Errore');
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet
      open={!!kind}
      onClose={onClose}
      title={kind === 'water' ? 'Aggiungi acqua' : 'Aggiungi caffè'}
      subtitle={
        kind === 'water'
          ? `Oggi: ${(current / 1000).toFixed(1)} L`
          : `Oggi: ${current} ${current === 1 ? 'tazza' : 'tazze'}`
      }
    >
      {kind === 'water' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2">
            {WATER_QUICK.map((q) => (
              <button
                key={q.ml}
                disabled={busy}
                onClick={() => addW(q.ml)}
                className="flex items-center gap-2 rounded-2xl bg-surface1 ring-1 ring-fg/10 px-3 py-3 hover:ring-sky-400/50 active:scale-[0.98] transition disabled:opacity-50"
              >
                <span className="text-2xl">{q.emoji}</span>
                <span className="text-left">
                  <span className="block text-sm font-medium text-fg">{q.label}</span>
                  <span className="block text-2xs text-fg-muted">{q.ml} ml</span>
                </span>
              </button>
            ))}
          </div>

          <div>
            <label className="mb-1 block text-sm text-fg-muted">Quantità libera (ml)</label>
            <div className="flex gap-2">
              <input
                type="number"
                inputMode="numeric"
                value={customMl}
                onChange={(e) => setCustomMl(e.target.value)}
                placeholder="es. 330"
                className="flex-1 rounded-2xl bg-surface1 px-4 py-2.5 text-base ring-1 ring-fg/10 focus:outline-none focus:ring-sky-400/40"
              />
              <Button
                variant="primary"
                loading={busy}
                disabled={!customMl || Number(customMl) === 0 || busy}
                onClick={() => addW(Math.trunc(Number(customMl)))}
              >
                Aggiungi
              </Button>
            </div>
          </div>

          {current > 0 && (
            <Button variant="ghost" size="sm" fullWidth disabled={busy} onClick={() => addW(-250)}>
              Correggi −250 ml
            </Button>
          )}
          {error && <p className="text-sm text-alert">{error}</p>}
        </div>
      )}

      {kind === 'coffee' && (
        <div className="space-y-4">
          <div className="flex items-center justify-center gap-4">
            <button
              disabled={busy || coffeeQty <= 1}
              onClick={() => setCoffeeQty((q) => Math.max(1, q - 1))}
              className="h-11 w-11 rounded-full bg-surface2 text-xl font-bold disabled:opacity-40"
            >
              −
            </button>
            <span className="text-3xl font-bold text-amber-700 dark:text-amber-300 w-16 text-center">
              {coffeeQty}
            </span>
            <button
              disabled={busy || coffeeQty >= 10}
              onClick={() => setCoffeeQty((q) => Math.min(10, q + 1))}
              className="h-11 w-11 rounded-full bg-surface2 text-xl font-bold disabled:opacity-40"
            >
              +
            </button>
          </div>
          <p className="text-center text-2xs text-fg-muted">
            {coffeeQty === 1 ? 'una tazza' : `${coffeeQty} tazze`} ☕
          </p>

          <Button variant="primary" fullWidth loading={busy} onClick={() => addC(coffeeQty)}>
            Aggiungi {coffeeQty === 1 ? 'il caffè' : `${coffeeQty} caffè`}
          </Button>

          {current > 0 && (
            <Button variant="ghost" size="sm" fullWidth disabled={busy} onClick={() => addC(-1)}>
              Correggi −1
            </Button>
          )}
          {error && <p className="text-sm text-alert">{error}</p>}
        </div>
      )}
    </BottomSheet>
  );
}
