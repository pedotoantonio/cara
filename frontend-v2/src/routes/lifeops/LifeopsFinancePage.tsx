// LifeopsFinancePage — overview finance: saldo, transazioni pending,
// transazioni recent, summary mese.

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, X, Plus } from '@phosphor-icons/react';
import { Button, Skeleton, useToast } from '@/design/components';
import {
  getAccounts,
  getTransactions,
  getFinanceSummary,
  getCategories,
  createTransaction,
  confirmTransaction,
  rejectTransaction,
  type Transaction,
  type FinanceCategory,
} from '@/api/lifeopsFinance';

export function LifeopsFinancePage() {
  const queryClient = useQueryClient();
  const toast = useToast();

  const [showAdd, setShowAdd] = useState(false);

  const accountsQ = useQuery({
    queryKey: ['lifeops', 'finance', 'accounts'],
    queryFn: getAccounts,
    staleTime: 60_000,
  });
  const pendingQ = useQuery({
    queryKey: ['lifeops', 'finance', 'tx', 'pending'],
    queryFn: () => getTransactions({ state: 'pending', limit: 50 }),
    staleTime: 10_000,
  });
  const recentQ = useQuery({
    queryKey: ['lifeops', 'finance', 'tx', 'recent'],
    queryFn: () => getTransactions({ state: 'confirmed', limit: 20 }),
    staleTime: 15_000,
  });
  const summaryQ = useQuery({
    queryKey: ['lifeops', 'finance', 'summary', 'month'],
    queryFn: () => {
      const now = new Date();
      const from = new Date(now.getFullYear(), now.getMonth(), 1).toISOString();
      return getFinanceSummary({ from });
    },
    staleTime: 30_000,
  });
  const categoriesQ = useQuery({
    queryKey: ['lifeops', 'finance', 'categories'],
    queryFn: () => getCategories('all'),
    staleTime: 5 * 60_000,
  });

  const confirmM = useMutation({
    mutationFn: (id: number) => confirmTransaction(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lifeops', 'finance'] });
      toast.push({ tone: 'mint', title: 'Confermata ✅' });
    },
  });
  const rejectM = useMutation({
    mutationFn: (id: number) => rejectTransaction(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lifeops', 'finance'] });
      toast.push({ tone: 'coral', title: 'Rifiutata' });
    },
  });

  const totalBalance = accountsQ.data?.reduce(
    (acc, a) => acc + a.balance_cents,
    0,
  ) ?? 0;

  return (
    <div className="px-4 md:px-6 lg:px-8 py-4 max-w-4xl mx-auto">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl text-text-primary">
            Le mie finanze
          </h1>
          <p className="text-sm text-text-muted">
            Spese, entrate, riepilogo mese.
          </p>
        </div>
        <Button
          size="sm"
          leftIcon={<Plus size={16} />}
          onClick={() => setShowAdd(true)}
        >
          Nuova
        </Button>
      </header>

      {/* Saldo + summary */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
        <Card title="Saldo totale" value={fmt(totalBalance / 100)} accent="emerald" />
        {summaryQ.data && (
          <>
            <Card
              title="Spese mese"
              value={fmt(parseFloat(summaryQ.data.total_expense))}
              accent="coral"
              sub={`${summaryQ.data.count_expense} transazioni`}
            />
            <Card
              title="Entrate mese"
              value={fmt(parseFloat(summaryQ.data.total_income))}
              accent="mint"
              sub={`${summaryQ.data.count_income} transazioni`}
            />
          </>
        )}
      </div>

      {/* Add form */}
      {showAdd && (
        <AddTransactionForm
          categories={categoriesQ.data ?? []}
          onClose={() => setShowAdd(false)}
          onCreated={() => {
            queryClient.invalidateQueries({ queryKey: ['lifeops', 'finance'] });
            setShowAdd(false);
          }}
        />
      )}

      {/* Pending — banner alto, attendono conferma */}
      {pendingQ.data && pendingQ.data.length > 0 && (
        <section className="mb-6">
          <h2 className="font-display text-lg text-text-primary mb-2">
            ⏳ In attesa di conferma ({pendingQ.data.length})
          </h2>
          <ul className="space-y-2">
            {pendingQ.data.map((tx) => (
              <PendingTxRow
                key={tx.id}
                tx={tx}
                onConfirm={() => confirmM.mutate(tx.id)}
                onReject={() => rejectM.mutate(tx.id)}
                busy={confirmM.isPending || rejectM.isPending}
              />
            ))}
          </ul>
        </section>
      )}

      {/* Recent */}
      <section>
        <h2 className="font-display text-lg text-text-primary mb-2">
          Movimenti recenti
        </h2>
        {recentQ.isLoading ? (
          <Skeleton className="h-16" />
        ) : !recentQ.data || recentQ.data.length === 0 ? (
          <p className="text-text-muted">Nessun movimento ancora.</p>
        ) : (
          <ul className="space-y-1.5">
            {recentQ.data.map((tx) => (
              <TxRow key={tx.id} tx={tx} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Card({
  title,
  value,
  accent,
  sub,
}: {
  title: string;
  value: string;
  accent: 'emerald' | 'coral' | 'mint';
  sub?: string;
}) {
  const accentMap: Record<string, string> = {
    emerald: 'text-emerald-500',
    coral: 'text-accent-coral',
    mint: 'text-accent-mint',
  };
  return (
    <div className="p-4 rounded-xl bg-bg-elevated border border-border-soft">
      <p className="text-xs text-text-muted mb-1">{title}</p>
      <p className={`font-display text-2xl ${accentMap[accent]}`}>{value}</p>
      {sub && <p className="text-xs text-text-muted mt-1">{sub}</p>}
    </div>
  );
}

function PendingTxRow({
  tx,
  onConfirm,
  onReject,
  busy,
}: {
  tx: Transaction;
  onConfirm: () => void;
  onReject: () => void;
  busy: boolean;
}) {
  return (
    <li className="p-3 rounded-xl border border-accent-sun/40 bg-accent-sun/8 flex items-center justify-between">
      <div className="flex-1">
        <p className="font-semibold text-text-primary">
          {fmt(parseFloat(tx.amount))} {tx.direction === 'expense' ? '· spesa' : '· entrata'}
        </p>
        <p className="text-sm text-text-muted">{tx.description || 'Senza descrizione'}</p>
      </div>
      <div className="flex gap-1">
        <button
          onClick={onConfirm}
          disabled={busy}
          className="p-2 rounded-md bg-accent-mint/20 text-accent-mint hover:bg-accent-mint/30"
          aria-label="Conferma"
        >
          <Check size={16} />
        </button>
        <button
          onClick={onReject}
          disabled={busy}
          className="p-2 rounded-md bg-accent-coral/15 text-accent-coral hover:bg-accent-coral/25"
          aria-label="Rifiuta"
        >
          <X size={16} />
        </button>
      </div>
    </li>
  );
}

function TxRow({ tx }: { tx: Transaction }) {
  const sign = tx.direction === 'income' ? '+' : '−';
  const color =
    tx.direction === 'income' ? 'text-accent-mint' : 'text-accent-coral';
  return (
    <li className="flex items-center gap-3 px-3 py-2 rounded-lg border border-border-soft bg-bg-elevated">
      <div className="flex-1 min-w-0">
        <p className="text-sm text-text-primary truncate">
          {tx.description || 'Senza descrizione'}
        </p>
        <p className="text-xs text-text-muted">
          {new Date(tx.happened_at).toLocaleDateString('it-IT', {
            day: 'numeric',
            month: 'short',
          })}
        </p>
      </div>
      <p className={`font-mono text-sm ${color}`}>
        {sign}
        {fmt(parseFloat(tx.amount))}
      </p>
    </li>
  );
}

function AddTransactionForm({
  categories,
  onClose,
  onCreated,
}: {
  categories: FinanceCategory[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const toast = useToast();
  const [amount, setAmount] = useState('');
  const [direction, setDirection] = useState<'expense' | 'income'>('expense');
  const [description, setDescription] = useState('');
  const [categorySlug, setCategorySlug] = useState<string>('');

  const filteredCats = categories.filter((c) => c.direction === direction);

  const createM = useMutation({
    mutationFn: () =>
      createTransaction({
        amount,
        direction,
        description: description || undefined,
        category_slug: categorySlug || undefined,
        state: 'confirmed',
      }),
    onSuccess: () => {
      toast.push({ tone: 'mint', title: 'Aggiunto' });
      onCreated();
    },
    onError: (err: Error) => {
      toast.push({ tone: 'coral', title: 'Errore', body: err.message });
    },
  });

  return (
    <div className="mb-4 p-4 rounded-xl border border-border-soft bg-bg-elevated">
      <div className="flex gap-2 mb-3">
        <button
          onClick={() => setDirection('expense')}
          className={`flex-1 px-3 py-1.5 rounded-md text-sm ${direction === 'expense' ? 'bg-accent-coral/15 border border-accent-coral/40 text-accent-coral' : 'bg-bg-base border border-border-soft text-text-muted'}`}
        >
          Spesa
        </button>
        <button
          onClick={() => setDirection('income')}
          className={`flex-1 px-3 py-1.5 rounded-md text-sm ${direction === 'income' ? 'bg-accent-mint/15 border border-accent-mint/40 text-accent-mint' : 'bg-bg-base border border-border-soft text-text-muted'}`}
        >
          Entrata
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2 mb-2">
        <input
          type="number"
          step="0.01"
          inputMode="decimal"
          placeholder="Importo (€)"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className="px-3 py-2 rounded-md border border-border-soft bg-bg-base text-text-primary"
        />
        <select
          value={categorySlug}
          onChange={(e) => setCategorySlug(e.target.value)}
          className="px-3 py-2 rounded-md border border-border-soft bg-bg-base text-text-primary"
        >
          <option value="">Categoria…</option>
          {filteredCats.map((c) => (
            <option key={c.id} value={c.slug}>
              {c.label}
            </option>
          ))}
        </select>
      </div>
      <input
        type="text"
        placeholder="Descrizione (opzionale)"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        className="w-full px-3 py-2 mb-3 rounded-md border border-border-soft bg-bg-base text-text-primary"
      />
      <div className="flex gap-2">
        <Button
          size="sm"
          fullWidth
          disabled={!amount || createM.isPending}
          onClick={() => createM.mutate()}
        >
          Aggiungi
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Annulla
        </Button>
      </div>
    </div>
  );
}

function fmt(eur: number): string {
  return `${eur.toFixed(2).replace('.', ',')}€`;
}
