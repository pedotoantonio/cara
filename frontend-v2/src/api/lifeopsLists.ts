// API client per i nuovi endpoint LifeOps M1.
// Backend: /api/v1/lifeops/lists/* + /pending/*

import { authFetch } from './client';

export type ListScope = 'user' | 'family' | 'shared';

export interface LifeopsList {
  id: number;
  user_id: number;
  family_id: number | null;
  slug: string;
  title: string;
  icon: string | null;
  scope: ListScope;
  color_token: string | null;
  sort_order: number;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LifeopsListItem {
  id: number;
  list_id: number;
  user_id: number;
  title: string;
  qty: number | null;
  unit: string | null;
  notes: string | null;
  done: boolean;
  done_at: string | null;
  done_by_user_id: number | null;
  sort_order: number;
  pending_approval: boolean;
  created_at: string;
  updated_at: string;
}

export interface PendingApproval {
  id: number;
  requested_by_user_id: number;
  supervisor_user_id: number | null;
  target_kind: string;
  target_id: number | null;
  target_payload: Record<string, unknown> | null;
  state: string;
  expires_at: string;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}

// ── Lists ───────────────────────────────────────────────────────────

export async function getLists(
  scope: 'user' | 'family' | 'all' = 'all',
  archived = false,
): Promise<LifeopsList[]> {
  const r = await authFetch(
    `/lifeops/lists?scope=${scope}&archived=${archived}`,
  );
  if (!r.ok) throw new Error(`getLists: ${r.status}`);
  return r.json();
}

export async function createList(payload: {
  slug: string;
  title: string;
  icon?: string | null;
  scope?: ListScope;
  color_token?: string | null;
}): Promise<LifeopsList> {
  const r = await authFetch('/lifeops/lists', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const msg = r.status === 409 ? 'slug già esistente' : `HTTP ${r.status}`;
    throw new Error(msg);
  }
  return r.json();
}

export async function updateList(
  listId: number,
  patch: Partial<{
    title: string;
    icon: string | null;
    color_token: string | null;
    sort_order: number;
    archived: boolean;
  }>,
): Promise<LifeopsList> {
  const r = await authFetch(`/lifeops/lists/${listId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(`updateList: ${r.status}`);
  return r.json();
}

export async function deleteList(listId: number): Promise<void> {
  const r = await authFetch(`/lifeops/lists/${listId}`, {
    method: 'DELETE',
  });
  if (!r.ok && r.status !== 204) {
    throw new Error(`deleteList: ${r.status}`);
  }
}

// ── List items ──────────────────────────────────────────────────────

export async function getItems(
  listId: number,
  includeDone = true,
): Promise<LifeopsListItem[]> {
  const r = await authFetch(
    `/lifeops/lists/${listId}/items?include_done=${includeDone}`,
  );
  if (!r.ok) throw new Error(`getItems: ${r.status}`);
  return r.json();
}

export async function addItem(
  listId: number,
  payload: {
    title: string;
    qty?: number | null;
    unit?: string | null;
    notes?: string | null;
  },
): Promise<LifeopsListItem> {
  const r = await authFetch(`/lifeops/lists/${listId}/items`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`addItem: ${r.status}`);
  return r.json();
}

export async function updateItem(
  listId: number,
  itemId: number,
  patch: Partial<{
    title: string;
    qty: number | null;
    unit: string | null;
    notes: string | null;
    done: boolean;
    sort_order: number;
  }>,
): Promise<LifeopsListItem> {
  const r = await authFetch(`/lifeops/lists/${listId}/items/${itemId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(`updateItem: ${r.status}`);
  return r.json();
}

export async function deleteItem(
  listId: number,
  itemId: number,
): Promise<void> {
  const r = await authFetch(`/lifeops/lists/${listId}/items/${itemId}`, {
    method: 'DELETE',
  });
  if (!r.ok && r.status !== 204) {
    throw new Error(`deleteItem: ${r.status}`);
  }
}

// ── Pending approvals ───────────────────────────────────────────────

export async function getPending(): Promise<PendingApproval[]> {
  const r = await authFetch('/lifeops/pending');
  if (!r.ok) throw new Error(`getPending: ${r.status}`);
  return r.json();
}

export async function approvePending(
  pendingId: number,
): Promise<PendingApproval> {
  const r = await authFetch(`/lifeops/pending/${pendingId}/approve`, {
    method: 'POST',
  });
  if (!r.ok) throw new Error(`approvePending: ${r.status}`);
  return r.json();
}

export async function rejectPending(
  pendingId: number,
): Promise<PendingApproval> {
  const r = await authFetch(`/lifeops/pending/${pendingId}/reject`, {
    method: 'POST',
  });
  if (!r.ok) throw new Error(`rejectPending: ${r.status}`);
  return r.json();
}
