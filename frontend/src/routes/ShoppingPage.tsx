import { useEffect, useState } from 'react';

import {
  ShoppingItem,
  clearBought,
  createShopping,
  deleteShopping,
  listShopping,
  updateShopping,
} from '../api/shopping';
import { CategoryHeader, Icon } from '../design';
import { useReactions } from '../lib/reactions';

export function ShoppingPage() {
  const reactions = useReactions();
  const [items, setItems] = useState<ShoppingItem[]>([]);
  const [draft, setDraft] = useState('');
  const [draftQty, setDraftQty] = useState('');
  const [hideBought, setHideBought] = useState(false);
  const [adding, setAdding] = useState(false);

  async function refresh() {
    try {
      setItems(await listShopping(!hideBought));
    } catch (e) {
      console.error(e);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hideBought]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || adding) return;
    setAdding(true);
    setDraft('');
    const qty = draftQty.trim();
    setDraftQty('');
    try {
      const t = await createShopping(text, qty || null);
      setItems((cur) => [t, ...cur]);
      reactions.trigger('shopping_added', { message: `Aggiunto: ${t.title}` });
    } catch (err) {
      console.error(err);
    } finally {
      setAdding(false);
    }
  }

  async function toggle(it: ShoppingItem) {
    try {
      const updated = await updateShopping(it.id, { bought: !it.bought });
      setItems((cur) => cur.map((x) => (x.id === it.id ? updated : x)));
      if (updated.bought) {
        reactions.trigger('shopping_bought', { message: `Preso: ${it.title}` });
      }
    } catch (err) {
      console.error(err);
    }
  }

  async function remove(id: string) {
    try {
      await deleteShopping(id);
      setItems((cur) => cur.filter((x) => x.id !== id));
    } catch (err) {
      console.error(err);
    }
  }

  async function clearAllBought() {
    try {
      await clearBought();
      await refresh();
    } catch (err) {
      console.error(err);
    }
  }

  const pending = items.filter((i) => !i.bought).length;
  const bought = items.length - pending;

  const totalKnown = pending + bought;
  const progressValue = totalKnown === 0 ? 0 : bought / totalKnown;
  const pillText = pending === 0
    ? 'Lista vuota'
    : `${pending} da comprare${bought > 0 ? ` · ${bought} presi` : ''}`;

  return (
    <main className="flex-1 flex flex-col px-4 md:px-6 py-4 gap-4">
      <CategoryHeader
        icon="shopping"
        title="Lista della spesa"
        subtitle={pending === 0 ? 'Aggiungi qualcosa qui sotto.' : 'Tocca il quadrato per dirla presa.'}
        pill={pillText}
        tint="terracotta"
        progress={totalKnown === 0 ? undefined : progressValue}
        progressLabel={totalKnown === 0 ? undefined : `${bought}/${totalKnown}`}
        progressCaption={totalKnown === 0 ? undefined : 'presi'}
        right={
          <label className="text-xs text-fg-muted flex items-center gap-2 cursor-pointer select-none bg-bg/60 backdrop-blur-sm rounded-pill px-3 py-2 ring-1 ring-fg/8">
            <input
              type="checkbox"
              checked={hideBought}
              onChange={(e) => setHideBought(e.target.checked)}
              className="accent-accent w-4 h-4"
            />
            <span className="hidden sm:inline">Nascondi presi</span>
            <span className="sm:hidden">✓</span>
          </label>
        }
      />

      <form onSubmit={add} className="flex flex-col sm:flex-row gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Cosa serve…"
          maxLength={200}
          className="flex-1 rounded-2xl bg-surface1 ring-1 ring-fg/8 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
        />
        <input
          value={draftQty}
          onChange={(e) => setDraftQty(e.target.value)}
          placeholder="Q.tà"
          maxLength={40}
          className="sm:w-24 rounded-2xl bg-surface1 ring-1 ring-fg/8 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
        />
        <button
          type="submit"
          disabled={!draft.trim() || adding}
          className="rounded-2xl bg-accent text-bg disabled:opacity-40 px-5 py-3 text-sm font-medium hover:bg-accent-dark transition shadow-sm"
        >
          Aggiungi
        </button>
      </form>

      <div className="flex-1 overflow-y-auto space-y-1.5">
        {items.length === 0 && (
          <div className="text-center text-fg-muted text-sm py-12 rounded-3xl bg-surface1 ring-1 ring-fg/6">
            La lista è vuota. Aggiungi un articolo qui sopra.
          </div>
        )}
        {items.map((it) => (
          <div
            key={it.id}
            className={`group flex items-center gap-3 rounded-2xl px-4 py-3 transition-all duration-200 ${
              it.bought
                ? 'bg-surface1/50 text-fg-muted ring-1 ring-fg/5'
                : 'bg-surface1 hover:bg-surface2 ring-1 ring-fg/8 hover:ring-fg/15 hover:shadow-sm'
            }`}
          >
            <button
              type="button"
              onClick={() => toggle(it)}
              aria-label={it.bought ? 'segna da comprare' : 'segna preso'}
              className={`shrink-0 h-6 w-6 rounded-md flex items-center justify-center transition-all duration-180 ease-spring ${
                it.bought
                  ? 'bg-ok text-ivory'
                  : 'ring-2 ring-fg/25 hover:ring-accent hover:bg-accent/10'
              }`}
            >
              {it.bought && <Icon name="check" size={14} />}
            </button>
            <span className={`flex-1 text-sm truncate ${it.bought ? 'line-through' : 'text-fg'}`}>
              {it.title}
            </span>
            {it.qty && (
              <span className="text-xs text-fg-muted px-2.5 py-0.5 rounded-pill bg-bg/60 ring-1 ring-fg/8 whitespace-nowrap">
                {it.qty}
              </span>
            )}
            <button
              type="button"
              onClick={() => {
                if (window.confirm(`Eliminare "${it.title}"?`)) {
                  void remove(it.id);
                }
              }}
              className="md:opacity-0 md:group-hover:opacity-100 opacity-60 hover:opacity-100 text-alert p-1.5 transition"
              aria-label={`Elimina ${it.title}`}
              title="Elimina"
            >
              <Icon name="trash" size={16} />
            </button>
          </div>
        ))}
      </div>

      {bought > 0 && (
        <div className="pt-2 flex justify-end">
          <button
            type="button"
            onClick={clearAllBought}
            className="text-xs text-fg-muted hover:text-alert px-3 py-1.5 rounded-pill bg-surface1 ring-1 ring-fg/8 transition"
          >
            Pulisci {bought} preso/i
          </button>
        </div>
      )}
    </main>
  );
}
