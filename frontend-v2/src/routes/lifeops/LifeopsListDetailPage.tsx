// LifeopsListDetailPage — items di una lista specifica.
//
// Pattern: header titolo + QuickAddInput + lista items + sezione "Fatti"
// collassabile. Pending approval mostrato con badge "in attesa".

import { useParams, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Trash, Lock } from '@phosphor-icons/react';
import { Skeleton, useToast } from '@/design/components';
import { QuickAddInput } from '@/components/lists/QuickAddInput';
import {
  getLists,
  getItems,
  addItem,
  updateItem,
  deleteItem,
  deleteList,
  type LifeopsListItem,
} from '@/api/lifeopsLists';

export function LifeopsListDetailPage() {
  const { slug = '' } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();

  // Trova la lista dallo slug
  const listsQ = useQuery({
    queryKey: ['lifeops', 'lists'],
    queryFn: () => getLists('all', false),
    staleTime: 30_000,
  });
  const list = listsQ.data?.find((l) => l.slug === slug);

  const itemsQ = useQuery({
    queryKey: ['lifeops', 'items', list?.id ?? 0],
    queryFn: () => getItems(list!.id, true),
    enabled: !!list,
    staleTime: 15_000,
  });

  const addM = useMutation({
    mutationFn: (title: string) => addItem(list!.id, { title }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({
        queryKey: ['lifeops', 'items', list!.id],
      });
      if (created.pending_approval) {
        toast.push({
          tone: 'sun',
          title: 'In attesa di approvazione',
          body: 'Un adulto deve approvare prima che l\'item sia visibile',
        });
      }
    },
  });

  const toggleM = useMutation({
    mutationFn: (vars: { item: LifeopsListItem; done: boolean }) =>
      updateItem(list!.id, vars.item.id, { done: vars.done }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['lifeops', 'items', list!.id],
      });
    },
  });

  const deleteM = useMutation({
    mutationFn: (itemId: number) => deleteItem(list!.id, itemId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['lifeops', 'items', list!.id],
      });
    },
  });

  const deleteListM = useMutation({
    mutationFn: () => deleteList(list!.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lifeops', 'lists'] });
      toast.push({ tone: 'mint', title: 'Lista eliminata' });
      navigate('/lifeops/lists');
    },
  });

  if (listsQ.isLoading || !list) {
    return (
      <div className="px-4 py-4 max-w-3xl mx-auto">
        <Skeleton className="h-8 w-1/2 mb-3" />
        <Skeleton className="h-16" />
      </div>
    );
  }

  const items = itemsQ.data ?? [];
  const todo = items.filter((it) => !it.done);
  const done = items.filter((it) => it.done);

  return (
    <div className="px-4 md:px-6 lg:px-8 py-4 max-w-3xl mx-auto">
      <header className="mb-4">
        <button
          onClick={() => navigate('/lifeops/lists')}
          className="inline-flex items-center gap-1 text-sm text-text-muted hover:text-text-primary mb-2"
        >
          <ArrowLeft size={14} />
          Le mie liste
        </button>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="font-display text-2xl text-text-primary">
              {list.title}
            </h1>
            <p className="text-xs text-text-muted mt-1">
              {list.scope === 'user' ? '🔒 Privata' : '👥 Famiglia'} · {items.length} elementi
            </p>
          </div>
          <button
            onClick={() => {
              if (confirm(`Elimino la lista "${list.title}"?`)) {
                deleteListM.mutate();
              }
            }}
            disabled={list.scope !== 'user'}
            title={list.scope !== 'user' ? 'Solo il proprietario può eliminare' : 'Elimina lista'}
            className="p-2 rounded-md text-text-muted hover:text-accent-coral disabled:opacity-30"
          >
            <Trash size={18} />
          </button>
        </div>
      </header>

      {/* Quick add */}
      <div className="mb-4">
        <QuickAddInput
          placeholder="Aggiungi alla lista — premi invio"
          onAdd={(title: string) => addM.mutate(title)}
          disabled={addM.isPending}
        />
      </div>

      {/* Items todo */}
      {itemsQ.isLoading ? (
        <Skeleton className="h-16 mb-2" />
      ) : todo.length === 0 && done.length === 0 ? (
        <p className="text-center text-text-muted py-8">
          La lista è vuota. Aggiungi il primo elemento.
        </p>
      ) : todo.length === 0 ? (
        <p className="text-center text-text-muted py-4">
          Tutto fatto ✅
        </p>
      ) : (
        <ul className="space-y-1.5">
          {todo.map((it) => (
            <ItemRow
              key={it.id}
              item={it}
              onToggle={(done) => toggleM.mutate({ item: it, done })}
              onDelete={() => deleteM.mutate(it.id)}
            />
          ))}
        </ul>
      )}

      {/* Done section */}
      {done.length > 0 && (
        <details className="mt-6">
          <summary className="text-sm text-text-muted cursor-pointer">
            Fatti ({done.length})
          </summary>
          <ul className="mt-2 space-y-1.5">
            {done.map((it) => (
              <ItemRow
                key={it.id}
                item={it}
                onToggle={(done) => toggleM.mutate({ item: it, done })}
                onDelete={() => deleteM.mutate(it.id)}
              />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ItemRow({
  item,
  onToggle,
  onDelete,
}: {
  item: LifeopsListItem;
  onToggle: (done: boolean) => void;
  onDelete: () => void;
}) {
  return (
    <li
      className={`flex items-center gap-3 px-3 py-2 rounded-lg border border-border-soft bg-bg-elevated ${item.pending_approval ? 'opacity-60' : ''}`}
    >
      <button
        onClick={() => onToggle(!item.done)}
        className={`w-6 h-6 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${item.done ? 'bg-accent-mint border-accent-mint text-white' : 'border-border-soft hover:border-accent-mint'}`}
        aria-label={item.done ? 'Marca non fatto' : 'Marca fatto'}
      >
        {item.done && '✓'}
      </button>
      <div className="flex-1 min-w-0">
        <p
          className={`text-sm ${item.done ? 'line-through text-text-muted' : 'text-text-primary'}`}
        >
          {item.title}
        </p>
        {item.pending_approval && (
          <span className="inline-flex items-center gap-1 text-xs text-accent-sun">
            <Lock size={10} /> In attesa di approvazione
          </span>
        )}
      </div>
      <button
        onClick={onDelete}
        className="p-1 rounded text-text-muted hover:text-accent-coral"
        aria-label="Elimina"
      >
        <Trash size={14} />
      </button>
    </li>
  );
}
