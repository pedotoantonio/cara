import { apiDelete, apiGet, apiPatch, apiPost } from './client';

export interface ShoppingItem {
  id: string;
  user_id: number;
  title: string;
  qty: number | null;
  bought: boolean;
  created_at: string;
  category?: string | null;
}

export async function listShopping(): Promise<ShoppingItem[]> {
  return apiGet<ShoppingItem[]>('/shopping');
}

export async function createShoppingItem(body: {
  title: string;
  qty?: number | null;
}): Promise<ShoppingItem> {
  return apiPost<ShoppingItem>('/shopping', body);
}

export async function updateShoppingItem(
  id: string,
  patch: { title?: string; bought?: boolean; qty?: number | null },
): Promise<ShoppingItem> {
  return apiPatch<ShoppingItem>(`/shopping/${id}`, patch);
}

export async function deleteShoppingItem(id: string): Promise<void> {
  return apiDelete(`/shopping/${id}`);
}

export async function clearBoughtShopping(): Promise<void> {
  await apiPost('/shopping/clear-bought', {}).catch(() => undefined);
}
