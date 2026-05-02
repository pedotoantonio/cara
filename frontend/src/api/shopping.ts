import { authFetch } from './auth';

const API = '/api/v1';

export interface ShoppingItem {
  id: string;
  title: string;
  qty: string | null;
  bought: boolean;
  created_at: string;
  bought_at: string | null;
}

export async function listShopping(includeBought = true): Promise<ShoppingItem[]> {
  const r = await authFetch(`${API}/shopping?include_bought=${includeBought}`);
  if (!r.ok) throw new Error(`list failed: ${r.status}`);
  return r.json();
}

export async function createShopping(title: string, qty?: string | null): Promise<ShoppingItem> {
  const body: Record<string, unknown> = { title };
  if (qty) body.qty = qty;
  const r = await authFetch(`${API}/shopping`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`create failed: ${r.status}`);
  return r.json();
}

export async function updateShopping(
  id: string,
  changes: { title?: string; qty?: string | null; bought?: boolean },
): Promise<ShoppingItem> {
  const r = await authFetch(`${API}/shopping/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  });
  if (!r.ok) throw new Error(`update failed: ${r.status}`);
  return r.json();
}

export async function deleteShopping(id: string): Promise<void> {
  const r = await authFetch(`${API}/shopping/${id}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`delete failed: ${r.status}`);
}

export async function clearBought(): Promise<{ removed: number }> {
  const r = await authFetch(`${API}/shopping/clear-bought`, { method: 'POST' });
  if (!r.ok) throw new Error(`clear failed: ${r.status}`);
  return r.json();
}
