import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence } from 'framer-motion';
import { Skeleton, useToast, Button } from '@/design/components';
import { QuickAddInput } from '@/components/lists/QuickAddInput';
import { ListItemCard } from '@/components/lists/ListItemCard';
import {
  clearBoughtShopping,
  createShoppingItem,
  deleteShoppingItem,
  listShopping,
  updateShoppingItem,
  type ShoppingItem,
} from '@/api/shopping';

export function ShoppingPage() {
  const queryClient = useQueryClient();
  const toast = useToast();

  const itemsQ = useQuery({
    queryKey: ['shopping'],
    queryFn: listShopping,
    staleTime: 30_000,
  });

  const addM = useMutation({
    mutationFn: (title: string) => createShoppingItem({ title }),
    onSuccess: (created) => {
      queryClient.setQueryData<ShoppingItem[]>(['shopping'], (prev) =>
        prev ? [created, ...prev] : [created],
      );
    },
    onError: (err) => toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message }),
  });

  const toggleM = useMutation({
    mutationFn: ({ id, bought }: { id: string; bought: boolean }) =>
      updateShoppingItem(id, { bought }),
    onMutate: async ({ id, bought }) => {
      await queryClient.cancelQueries({ queryKey: ['shopping'] });
      const prev = queryClient.getQueryData<ShoppingItem[]>(['shopping']);
      queryClient.setQueryData<ShoppingItem[]>(['shopping'], (p) =>
        p ? p.map((x) => (x.id === id ? { ...x, bought } : x)) : p,
      );
      return { prev };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['shopping'], ctx.prev);
      toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message });
    },
  });

  const deleteM = useMutation({
    mutationFn: (id: string) => deleteShoppingItem(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ['shopping'] });
      const prev = queryClient.getQueryData<ShoppingItem[]>(['shopping']);
      queryClient.setQueryData<ShoppingItem[]>(['shopping'], (p) =>
        p ? p.filter((x) => x.id !== id) : p,
      );
      return { prev };
    },
    onError: (err, _id, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['shopping'], ctx.prev);
      toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message });
    },
  });

  const clearBoughtM = useMutation({
    mutationFn: () => clearBoughtShopping(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['shopping'] });
      toast.push({ tone: 'mint', title: 'Lista pulita' });
    },
  });

  const items = itemsQ.data ?? [];
  const toBuy = items.filter((x) => !x.bought);
  const bought = items.filter((x) => x.bought);

  return (
    <div className="container-app py-4 space-y-4">
      <QuickAddInput
        placeholder="Aggiungi alla spesa — es. pomodori"
        onAdd={async (t) => { await addM.mutateAsync(t); }}
      />

      {itemsQ.isLoading && (
        <ul className="space-y-2">
          {[1, 2, 3].map((i) => (
            <li key={i}>
              <Skeleton className="h-14 w-full" />
            </li>
          ))}
        </ul>
      )}

      {!itemsQ.isLoading && items.length === 0 && (
        <p className="text-text-muted text-center py-8 text-sm">
          Lista vuota. Aggiungi cose qui sopra.
        </p>
      )}

      {toBuy.length > 0 && (
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted mb-2 px-1">
            Da comprare ({toBuy.length})
          </h2>
          <ul className="space-y-2">
            <AnimatePresence>
              {toBuy.map((x) => (
                <ListItemCard
                  key={x.id}
                  done={x.bought}
                  accent="rose"
                  onToggleDone={(next) => toggleM.mutate({ id: x.id, bought: next })}
                  onDelete={() => deleteM.mutate(x.id)}
                >
                  <p className="font-medium">{x.title}</p>
                  {x.qty != null && x.qty > 1 && (
                    <p className="text-xs text-text-muted">× {x.qty}</p>
                  )}
                </ListItemCard>
              ))}
            </AnimatePresence>
          </ul>
        </section>
      )}

      {bought.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-2 px-1">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
              Già comprate ({bought.length})
            </h2>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => clearBoughtM.mutate()}
              loading={clearBoughtM.isPending}
            >
              Pulisci
            </Button>
          </div>
          <ul className="space-y-2">
            <AnimatePresence>
              {bought.map((x) => (
                <ListItemCard
                  key={x.id}
                  done={x.bought}
                  accent="rose"
                  onToggleDone={(next) => toggleM.mutate({ id: x.id, bought: next })}
                  onDelete={() => deleteM.mutate(x.id)}
                >
                  <p className="font-medium">{x.title}</p>
                </ListItemCard>
              ))}
            </AnimatePresence>
          </ul>
        </section>
      )}
    </div>
  );
}
