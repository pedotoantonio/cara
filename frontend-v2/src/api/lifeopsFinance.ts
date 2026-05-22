// API client per LifeOps Finance M2.

import { authFetch } from './client';

export interface Account {
  id: number;
  user_id: number;
  name: string;
  kind: string;
  currency: string;
  balance_cents: number;
  archived_at: string | null;
  created_at: string;
}

export interface FinanceCategory {
  id: number;
  family_id: number | null;
  slug: string;
  label: string;
  direction: 'expense' | 'income';
  icon: string | null;
  color_token: string | null;
}

export interface Transaction {
  id: number;
  user_id: number;
  account_id: number;
  category_id: number | null;
  amount: string;
  direction: 'expense' | 'income' | 'transfer';
  happened_at: string;
  description: string | null;
  state: 'pending' | 'confirmed' | 'rejected';
  confirmed_at: string | null;
  created_at: string;
}

export interface FinanceSummary {
  total_expense: string;
  total_income: string;
  net: string;
  count_expense: number;
  count_income: number;
  by_category: Array<{ category_id: number | null; amount: string; count: number }>;
}

// Accounts
export async function getAccounts(): Promise<Account[]> {
  const r = await authFetch('/lifeops/finance/accounts');
  if (!r.ok) throw new Error(`getAccounts: ${r.status}`);
  return r.json();
}

export async function createAccount(payload: {
  name: string;
  kind?: string;
  currency?: string;
}): Promise<Account> {
  const r = await authFetch('/lifeops/finance/accounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`createAccount: ${r.status}`);
  return r.json();
}

// Categories
export async function getCategories(
  direction: 'expense' | 'income' | 'all' = 'all',
): Promise<FinanceCategory[]> {
  const r = await authFetch(`/lifeops/finance/categories?direction=${direction}`);
  if (!r.ok) throw new Error(`getCategories: ${r.status}`);
  return r.json();
}

// Transactions
export async function getTransactions(filters: {
  state?: 'pending' | 'confirmed' | 'rejected' | 'all';
  direction?: 'expense' | 'income' | 'transfer' | 'all';
  account_id?: number;
  limit?: number;
} = {}): Promise<Transaction[]> {
  const params = new URLSearchParams();
  if (filters.state) params.set('state', filters.state);
  if (filters.direction) params.set('direction', filters.direction);
  if (filters.account_id) params.set('account_id', String(filters.account_id));
  if (filters.limit) params.set('limit', String(filters.limit));
  const r = await authFetch(`/lifeops/finance/transactions?${params}`);
  if (!r.ok) throw new Error(`getTransactions: ${r.status}`);
  return r.json();
}

export async function createTransaction(payload: {
  amount: string;
  direction: 'expense' | 'income';
  category_slug?: string;
  description?: string;
  happened_at?: string;
  state?: 'pending' | 'confirmed';
}): Promise<Transaction> {
  const r = await authFetch('/lifeops/finance/transactions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`createTransaction: ${r.status}`);
  return r.json();
}

export async function confirmTransaction(txId: number): Promise<Transaction> {
  const r = await authFetch(`/lifeops/finance/transactions/${txId}/confirm`, {
    method: 'POST',
  });
  if (!r.ok) throw new Error(`confirmTransaction: ${r.status}`);
  return r.json();
}

export async function rejectTransaction(txId: number): Promise<Transaction> {
  const r = await authFetch(`/lifeops/finance/transactions/${txId}/reject`, {
    method: 'POST',
  });
  if (!r.ok) throw new Error(`rejectTransaction: ${r.status}`);
  return r.json();
}

export async function deleteTransaction(txId: number): Promise<void> {
  const r = await authFetch(`/lifeops/finance/transactions/${txId}`, {
    method: 'DELETE',
  });
  if (!r.ok && r.status !== 204) throw new Error(`deleteTransaction: ${r.status}`);
}

export async function getFinanceSummary(period?: {
  from?: string;
  to?: string;
}): Promise<FinanceSummary> {
  const params = new URLSearchParams();
  if (period?.from) params.set('from_iso', period.from);
  if (period?.to) params.set('to_iso', period.to);
  const r = await authFetch(`/lifeops/finance/summary?${params}`);
  if (!r.ok) throw new Error(`getFinanceSummary: ${r.status}`);
  return r.json();
}
