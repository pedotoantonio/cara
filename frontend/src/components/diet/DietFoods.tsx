// DietFoods — catalogo alimenti consultabile con badge di status
// (consigliato / da moderare / sconsigliato), filtri per categoria
// proteica e ricerca per nome.

import { useEffect, useMemo, useState } from 'react';

import {
  STATUS_LABEL,
  getFoods,
  type FoodItem,
  type FoodStatus,
  type ProteinCategory,
} from '../../api/diet';
import { Badge, Card } from '../../design';

const CATEGORIES: { key: ProteinCategory | 'all'; label: string }[] = [
  { key: 'all', label: 'Tutti' },
  { key: 'legumi', label: 'Legumi' },
  { key: 'pesce', label: 'Pesce' },
  { key: 'carne', label: 'Carne' },
  { key: 'uova', label: 'Uova' },
  { key: 'formaggio', label: 'Formaggio' },
];

const STATUS_TONE: Record<FoodStatus, 'ok' | 'accent' | 'alert'> = {
  consigliato: 'ok',
  da_moderare: 'accent',
  sconsigliato: 'alert',
};

export function DietFoods() {
  const [foods, setFoods] = useState<FoodItem[]>([]);
  const [cat, setCat] = useState<ProteinCategory | 'all'>('all');
  const [q, setQ] = useState('');

  useEffect(() => {
    getFoods(cat === 'all' ? undefined : { category: cat })
      .then(setFoods)
      .catch(() => setFoods([]));
  }, [cat]);

  const filtered = useMemo(
    () => foods.filter((f) => f.name.toLowerCase().includes(q.toLowerCase())),
    [foods, q],
  );

  return (
    <div className="space-y-4">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Cerca un alimento…"
        className="w-full rounded-full bg-surface1 ring-1 ring-fg/10 px-4 h-11 focus:outline-none focus:ring-accent/40"
      />

      <div className="flex gap-1.5 overflow-x-auto no-scrollbar">
        {CATEGORIES.map((c) => (
          <button
            key={c.key}
            onClick={() => setCat(c.key)}
            className={`shrink-0 rounded-full px-3 h-8 text-sm transition ${
              cat === c.key ? 'bg-accent text-ivory' : 'bg-surface2 text-fg-muted'
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      <p className="text-2xs text-fg-muted">
        {filtered.length} alimenti · grammature a crudo, al netto degli scarti
      </p>

      <div className="space-y-2">
        {filtered.map((f) => (
          <Card key={f.id} className="py-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="font-medium capitalize">{f.name}</div>
                {f.notes && <div className="text-2xs text-fg-muted truncate">{f.notes}</div>}
              </div>
              <Badge tone={STATUS_TONE[f.status]} size="sm">
                {STATUS_LABEL[f.status]}
              </Badge>
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2 text-2xs text-fg-muted">
              {f.portion_primo_g && <span>primo {f.portion_primo_g}g</span>}
              {f.portion_secondo_g && <span>secondo {f.portion_secondo_g}g</span>}
              {!f.portion_primo_g && f.default_portion_g && (
                <span>porzione {f.default_portion_g}g</span>
              )}
              {f.kcal_per_100g && <span>≈{f.kcal_per_100g} kcal/100g</span>}
            </div>
          </Card>
        ))}
        {filtered.length === 0 && (
          <p className="text-fg-muted text-sm text-center py-8">Nessun alimento.</p>
        )}
      </div>
    </div>
  );
}
