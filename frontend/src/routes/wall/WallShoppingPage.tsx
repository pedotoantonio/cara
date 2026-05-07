// Shopping list page for the Wall — read + write, no auth (LAN only).
//
// Items come pre-grouped by category from the backend (auto-classifier
// scans the title against an Italian lexicon). Each item is editable
// inline: title, qty, owner, bought toggle. New items can be added via
// the input at the top.

import { useEffect, useState } from 'react';

import {
  clearBoughtShopping,
  createShopping,
  deleteShopping,
  fetchShopping,
  patchShopping,
} from '../../api/wall';
import type { WallShopping, WallShoppingItem, WallUser } from '../../api/wall';
import { OwnerChip } from '../../components/wall/OwnerChip';

export function WallShoppingPage() {
  const [data, setData] = useState<WallShopping | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState('');
  const [newQty, setNewQty] = useState('');
  const [newOwner, setNewOwner] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      const d = await fetchShopping();
      setData(d);
      setError(null);
      if (newOwner === null && d.family.length > 0) {
        setNewOwner(d.family[0].id);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    void refresh();
    const id = window.setInterval(refresh, 30_000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function addItem() {
    const t = newTitle.trim();
    if (!t) return;
    setBusy(true);
    try {
      await createShopping({
        title: t,
        qty: newQty.trim() || null,
        ...(newOwner ? { owner_id: newOwner } : {}),
      });
      setNewTitle('');
      setNewQty('');
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function clearBought() {
    if (!data || data.totals.bought === 0) return;
    if (!window.confirm(`Rimuovere ${data.totals.bought} prodotti già comprati?`)) {
      return;
    }
    setBusy(true);
    try {
      await clearBoughtShopping();
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  if (!data) {
    return (
      <div className="text-fg-muted text-center py-8 animate-breathe">
        {error ? `⚠ ${error}` : 'Carico la lista della spesa…'}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5 mt-2 max-w-3xl mx-auto pb-20">
      {/* Add input */}
      <section className="rounded-xl bg-surface2/40 p-4 flex flex-col gap-3">
        <h2
          className="font-display text-fg"
          style={{ fontSize: 'clamp(20px, 1.8vw, 26px)' }}
        >
          Aggiungi un prodotto
        </h2>
        <div className="flex flex-wrap gap-2">
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void addItem();
            }}
            placeholder="Es. Pane, Mele, Latte…"
            className="flex-1 min-w-[220px] bg-bg/70 rounded-md px-3 py-2 text-md"
            autoFocus
          />
          <input
            value={newQty}
            onChange={(e) => setNewQty(e.target.value)}
            placeholder="Qta (1, 500g, …)"
            className="w-32 bg-bg/70 rounded-md px-3 py-2 text-md"
          />
          <select
            value={newOwner ?? ''}
            onChange={(e) => setNewOwner(parseInt(e.target.value, 10) || null)}
            className="bg-bg/70 rounded-md px-3 py-2 text-md"
          >
            {data.family.map((u) => (
              <option key={u.id} value={u.id}>
                {u.emoji} {u.display_name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={addItem}
            disabled={busy || !newTitle.trim()}
            className="rounded-pill bg-accent text-bg px-5 py-2 disabled:opacity-50"
          >
            Aggiungi
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-fg-muted text-sm">
          <span>
            {data.totals.todo} da comprare · {data.totals.bought} comprati
          </span>
          {data.totals.bought > 0 && (
            <button
              type="button"
              onClick={clearBought}
              className="ml-auto text-alert hover:underline"
            >
              Rimuovi i comprati
            </button>
          )}
        </div>
      </section>

      {error && (
        <div className="text-alert text-sm text-center">⚠ {error}</div>
      )}

      {/* Groups */}
      {data.groups.length === 0 && data.bought.length === 0 && (
        <div className="rounded-xl bg-surface2/40 px-6 py-8 text-center text-fg-muted">
          La lista è vuota. Aggiungi qualcosa qui sopra.
        </div>
      )}
      {data.groups.map((g) => (
        <CategoryGroup
          key={g.name}
          name={g.name}
          items={g.items}
          family={data.family}
          onChanged={refresh}
        />
      ))}

      {/* Bought collapsible */}
      {data.bought.length > 0 && (
        <details className="rounded-xl bg-surface2/30 px-4 py-3" open={false}>
          <summary className="cursor-pointer text-fg-soft text-sm select-none">
            Già comprati ({data.bought.length})
          </summary>
          <div className="flex flex-col gap-1.5 mt-3">
            {data.bought.map((it) => (
              <ShoppingRow
                key={it.id}
                item={it}
                family={data.family}
                onChanged={refresh}
                bought
              />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function CategoryGroup({
  name,
  items,
  family,
  onChanged,
}: {
  name: string;
  items: WallShoppingItem[];
  family: WallUser[];
  onChanged: () => void;
}) {
  return (
    <section className="rounded-xl bg-surface2/40 p-4 flex flex-col gap-2">
      <header className="flex items-baseline justify-between">
        <h3
          className="font-display text-fg"
          style={{ fontSize: 'clamp(16px, 1.4vw, 20px)' }}
        >
          {name}
        </h3>
        <span className="text-fg-muted text-xs">
          {items.length} prodot{items.length === 1 ? 'to' : 'ti'}
        </span>
      </header>
      <div className="flex flex-col gap-1.5">
        {items.map((it) => (
          <ShoppingRow
            key={it.id}
            item={it}
            family={family}
            onChanged={onChanged}
          />
        ))}
      </div>
    </section>
  );
}

function ShoppingRow({
  item,
  family,
  onChanged,
  bought,
}: {
  item: WallShoppingItem;
  family: WallUser[];
  onChanged: () => void;
  bought?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [qty, setQty] = useState(item.qty ?? '');
  const [ownerId, setOwnerId] = useState<number>(item.owner_id);
  const [busy, setBusy] = useState(false);

  async function toggleBought() {
    setBusy(true);
    try {
      await patchShopping(item.id, { bought: !item.bought });
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    const t = title.trim();
    if (!t) return;
    setBusy(true);
    try {
      await patchShopping(item.id, {
        title: t,
        qty: qty.trim() || null,
        owner_id: ownerId,
      });
      setEditing(false);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Rimuovere "${item.title}"?`)) return;
    setBusy(true);
    try {
      await deleteShopping(item.id);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <div
        className="flex flex-wrap items-center gap-2 px-3 py-2 rounded-md bg-bg/60"
        style={{ borderLeft: `4px solid ${item.owner?.color ?? '#94a3b8'}` }}
      >
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="flex-1 min-w-[150px] bg-surface2/60 rounded-md px-2 py-1.5 text-sm"
          autoFocus
        />
        <input
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          placeholder="qta"
          className="w-20 bg-surface2/60 rounded-md px-2 py-1.5 text-sm"
        />
        <select
          value={ownerId}
          onChange={(e) => setOwnerId(parseInt(e.target.value, 10))}
          className="bg-surface2/60 rounded-md px-2 py-1.5 text-sm"
        >
          {family.map((u) => (
            <option key={u.id} value={u.id}>
              {u.emoji} {u.display_name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={save}
          disabled={busy || !title.trim()}
          className="rounded-pill bg-accent text-bg px-3 py-1.5 text-sm"
        >
          Salva
        </button>
        <button
          type="button"
          onClick={() => {
            setEditing(false);
            setTitle(item.title);
            setQty(item.qty ?? '');
            setOwnerId(item.owner_id);
          }}
          className="rounded-pill text-fg-muted px-3 py-1.5 text-sm"
        >
          Annulla
        </button>
      </div>
    );
  }

  return (
    <div
      className={[
        'flex items-center gap-3 px-3 py-2 rounded-md bg-bg/40',
        bought ? 'opacity-60' : '',
      ].join(' ')}
      style={{ borderLeft: `4px solid ${item.owner?.color ?? '#94a3b8'}` }}
    >
      <input
        type="checkbox"
        checked={item.bought}
        onChange={toggleBought}
        disabled={busy}
        className="w-5 h-5 flex-shrink-0"
      />
      <div className="flex-1 min-w-0">
        <span
          className={[
            'block truncate',
            item.bought ? 'line-through text-fg-muted' : 'text-fg',
          ].join(' ')}
          style={{ fontSize: 'clamp(15px, 1.2vw, 18px)' }}
        >
          {item.title}
          {item.qty && (
            <span className="ml-2 text-fg-muted text-sm">· {item.qty}</span>
          )}
        </span>
      </div>
      <OwnerChip user={item.owner} variant="compact" />
      <button
        type="button"
        onClick={() => setEditing(true)}
        disabled={busy}
        className="text-fg-muted hover:text-fg text-sm px-2"
        title="Modifica"
      >
        ✎
      </button>
      <button
        type="button"
        onClick={remove}
        disabled={busy}
        className="text-fg-muted hover:text-alert text-sm px-2"
        title="Elimina"
      >
        ×
      </button>
    </div>
  );
}
