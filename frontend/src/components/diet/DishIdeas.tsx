// DishIdeas — "Cosa cucino?": piatti cucinabili dagli ingredienti che hai
// in lista spesa, con calorie stimate. Tap su un piatto → ricetta completa
// in un BottomSheet, con possibilità di aggiungere alla spesa i mancanti.

import { useCallback, useEffect, useState } from 'react';

import {
  type DishProposal,
  type MealType,
  type RecipeDetail,
  addDishMissingToShopping,
  getDishRecipe,
  getDishes,
} from '../../api/diet';
import { Badge, BottomSheet, Button, Card, Icon } from '../../design';

interface Props {
  meal: MealType;
}

export function DishIdeas({ meal }: Props) {
  const [dishes, setDishes] = useState<DishProposal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<DishProposal | null>(null);

  const load = useCallback(() => {
    setError(null);
    getDishes(meal)
      .then(setDishes)
      .catch((e) => setError(e instanceof Error ? e.message : 'Errore'));
  }, [meal]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return <Card><p className="text-sm text-fg-muted">Non riesco a proporre piatti ora.</p></Card>;
  }
  if (!dishes) {
    return <Card><p className="text-sm text-fg-muted">Penso a cosa cucinare…</p></Card>;
  }
  if (dishes.length === 0) {
    return (
      <Card>
        <div className="flex items-center gap-2 mb-1">
          <Icon name="heart" size={18} />
          <h2 className="font-semibold">Cosa cucino?</h2>
        </div>
        <p className="text-sm text-fg-muted">
          Aggiungi qualche ingrediente alla lista della spesa e ti proporrò dei piatti.
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <div className="flex items-center gap-2 mb-3">
        <Icon name="heart" size={18} />
        <h2 className="font-semibold">Cosa cucino?</h2>
        <span className="text-2xs text-fg-muted ml-auto">dai tuoi ingredienti</span>
      </div>

      <ul className="space-y-2">
        {dishes.map((d) => (
          <li key={d.slug}>
            <button
              onClick={() => setActive(d)}
              className="w-full text-left rounded-2xl bg-surface1 ring-1 ring-fg/8 px-3 py-2.5 hover:ring-accent/40 active:scale-[0.99] transition"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-fg leading-tight">{d.title}</span>
                {d.kcal_estimate != null && (
                  <span className="shrink-0 text-sm font-semibold text-accent">
                    {d.kcal_estimate} kcal
                  </span>
                )}
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                {d.missing.length === 0 ? (
                  <Badge tone="ok">hai tutto</Badge>
                ) : (
                  <Badge tone="neutral">mancano {d.missing.length}</Badge>
                )}
                {d.ingredients.slice(0, 3).map((i) => (
                  <span
                    key={i.name}
                    className={`text-2xs rounded-pill px-2 py-0.5 ${
                      i.have ? 'bg-ok/12 text-ok' : 'bg-surface2 text-fg-muted'
                    }`}
                  >
                    {i.have ? '✓' : '+'} {i.name}
                  </span>
                ))}
              </div>
            </button>
          </li>
        ))}
      </ul>

      <RecipeSheet
        dish={active}
        onClose={() => setActive(null)}
        onShoppingChanged={load}
      />
    </Card>
  );
}

function RecipeSheet({
  dish,
  onClose,
  onShoppingChanged,
}: {
  dish: DishProposal | null;
  onClose: () => void;
  onShoppingChanged: () => void;
}) {
  const [recipe, setRecipe] = useState<RecipeDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState(false);

  useEffect(() => {
    if (!dish) {
      setRecipe(null);
      setAdded(false);
      return;
    }
    setLoading(true);
    getDishRecipe(dish.title)
      .then(setRecipe)
      .catch(() => setRecipe(null))
      .finally(() => setLoading(false));
  }, [dish]);

  async function addMissing() {
    if (!dish || dish.missing.length === 0) return;
    setAdding(true);
    try {
      await addDishMissingToShopping(dish.missing);
      setAdded(true);
      onShoppingChanged();
    } finally {
      setAdding(false);
    }
  }

  const steps = recipe?.steps
    ? recipe.steps.split('\n').filter((s) => s.trim())
    : [];

  return (
    <BottomSheet
      open={!!dish}
      onClose={onClose}
      title={dish?.title ?? ''}
      subtitle={dish?.kcal_estimate != null ? `≈ ${dish.kcal_estimate} kcal` : undefined}
    >
      {!dish ? null : loading ? (
        <p className="text-sm text-fg-muted">Preparo la ricetta…</p>
      ) : (
        <div className="space-y-4">
          {/* Ingredienti */}
          <div>
            <h3 className="text-sm font-semibold mb-2">Ingredienti</h3>
            <ul className="space-y-1.5">
              {(recipe?.ingredients?.length
                ? recipe.ingredients
                : dish.ingredients.map((i) => ({ item: i.name, qty: i.portion_g ? `${i.portion_g}g` : null }))
              ).map((ing, i) => (
                <li key={i} className="flex items-center justify-between text-sm">
                  <span className="text-fg">{ing.item}</span>
                  {ing.qty && <span className="text-fg-muted text-2xs">{ing.qty}</span>}
                </li>
              ))}
            </ul>
          </div>

          {/* Mancanti → aggiungi alla spesa */}
          {dish.missing.length > 0 && (
            <div className="rounded-2xl bg-amber-500/10 ring-1 ring-amber-500/20 px-3 py-2.5">
              <p className="text-sm text-amber-700 dark:text-amber-300 mb-2">
                Ti mancano: {dish.missing.join(', ')}
              </p>
              <Button
                variant="surface"
                size="sm"
                fullWidth
                iconLeft="shopping"
                loading={adding}
                disabled={added}
                onClick={addMissing}
              >
                {added ? 'Aggiunti alla spesa ✓' : 'Aggiungi i mancanti alla spesa'}
              </Button>
            </div>
          )}

          {/* Procedimento */}
          {steps.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold mb-2">Procedimento</h3>
              <ol className="space-y-2">
                {steps.map((s, i) => (
                  <li key={i} className="text-sm text-fg leading-relaxed">
                    {s.replace(/^\d+\.\s*/, `${i + 1}. `)}
                  </li>
                ))}
              </ol>
            </div>
          )}

          <p className="text-2xs text-fg-muted">
            Calorie indicative. Olio EVO a crudo, verdura di stagione.
          </p>
        </div>
      )}
    </BottomSheet>
  );
}
