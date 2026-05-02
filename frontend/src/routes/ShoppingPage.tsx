import { useEffect, useState } from 'react';

import {
  ShoppingItem,
  clearBought,
  createShopping,
  deleteShopping,
  listShopping,
  updateShopping,
} from '../api/shopping';
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

  return (
    <main className="flex-1 flex flex-col">
      <header className="border-b border-slate-800 px-4 md:px-6 py-4 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-medium">Lista della spesa 🛒</h1>
          <p className="text-xs text-slate-500 mt-0.5 truncate">
            {pending === 0 ? 'lista vuota' : `${pending} da comprare`}
            {bought > 0 && <span> · {bought} presi</span>}
          </p>
        </div>
        <label className="text-xs text-slate-400 flex items-center gap-2 cursor-pointer shrink-0">
          <input
            type="checkbox"
            checked={hideBought}
            onChange={(e) => setHideBought(e.target.checked)}
            className="accent-emerald-500"
          />
          <span className="hidden sm:inline">Nascondi presi</span>
          <span className="sm:hidden">Nascondi ✓</span>
        </label>
      </header>

      <form onSubmit={add} className="border-b border-slate-800 p-3 md:p-4 flex flex-col sm:flex-row gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Cosa serve…"
          maxLength={200}
          className="flex-1 rounded-xl bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
        />
        <input
          value={draftQty}
          onChange={(e) => setDraftQty(e.target.value)}
          placeholder="Q.tà"
          maxLength={40}
          className="sm:w-24 rounded-xl bg-slate-800 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
        />
        <button
          type="submit"
          disabled={!draft.trim() || adding}
          className="rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-4 py-2 text-sm font-medium"
        >
          Aggiungi
        </button>
      </form>

      <div className="flex-1 overflow-y-auto p-4 space-y-1">
        {items.length === 0 && (
          <div className="text-center text-slate-500 text-sm py-12">
            La lista è vuota. Aggiungi un articolo qui sopra.
          </div>
        )}
        {items.map((it) => (
          <div
            key={it.id}
            className={`group flex items-center gap-3 rounded-xl px-3 py-2 ${
              it.bought ? 'bg-slate-800/40 text-slate-500' : 'bg-slate-800/60'
            }`}
          >
            <button
              type="button"
              onClick={() => toggle(it)}
              aria-label={it.bought ? 'segna da comprare' : 'segna preso'}
              className={`w-5 h-5 shrink-0 rounded-md border ${
                it.bought
                  ? 'bg-emerald-500 border-emerald-500 flex items-center justify-center text-white text-xs'
                  : 'border-slate-600 hover:border-emerald-500'
              }`}
            >
              {it.bought ? '✓' : ''}
            </button>
            <span className={`flex-1 text-sm truncate ${it.bought ? 'line-through' : ''}`}>
              {it.title}
            </span>
            {it.qty && (
              <span className="text-[11px] text-slate-400 px-2 py-0.5 rounded-full bg-slate-700/60 whitespace-nowrap">
                {it.qty}
              </span>
            )}
            <button
              type="button"
              onClick={() => remove(it.id)}
              className="md:opacity-0 md:group-hover:opacity-100 text-slate-500 hover:text-rose-400 text-xs transition"
              aria-label="elimina"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      {bought > 0 && (
        <div className="border-t border-slate-800 p-3 flex justify-end">
          <button
            type="button"
            onClick={clearAllBought}
            className="text-xs text-slate-400 hover:text-rose-400"
          >
            Pulisci {bought} preso/i
          </button>
        </div>
      )}
    </main>
  );
}
