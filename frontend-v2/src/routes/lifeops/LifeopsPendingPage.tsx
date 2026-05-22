// LifeopsPendingPage — admin/supervisor view per approvare richieste
// dei bambini.
//
// L'utente con is_supervisor=true vede qui le richieste in pending
// (item aggiunti da child a liste family) e può approvare/rifiutare.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, X, Lock } from '@phosphor-icons/react';
import { Button, Skeleton, useToast } from '@/design/components';
import {
  getPending,
  approvePending,
  rejectPending,
  type PendingApproval,
} from '@/api/lifeopsLists';

export function LifeopsPendingPage() {
  const queryClient = useQueryClient();
  const toast = useToast();

  const pendingQ = useQuery({
    queryKey: ['lifeops', 'pending'],
    queryFn: getPending,
    staleTime: 10_000,
  });

  const approveM = useMutation({
    mutationFn: (id: number) => approvePending(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lifeops', 'pending'] });
      queryClient.invalidateQueries({ queryKey: ['lifeops', 'items'] });
      toast.push({ tone: 'mint', title: 'Approvato ✅' });
    },
  });

  const rejectM = useMutation({
    mutationFn: (id: number) => rejectPending(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lifeops', 'pending'] });
      queryClient.invalidateQueries({ queryKey: ['lifeops', 'items'] });
      toast.push({ tone: 'coral', title: 'Rifiutato' });
    },
  });

  return (
    <div className="px-4 md:px-6 lg:px-8 py-4 max-w-3xl mx-auto">
      <header className="mb-4">
        <h1 className="font-display text-2xl text-text-primary">
          Approvazioni in attesa
        </h1>
        <p className="text-sm text-text-muted">
          Richieste di Sara e Matteo da approvare o rifiutare.
        </p>
      </header>

      {pendingQ.isLoading ? (
        <Skeleton className="h-24" />
      ) : pendingQ.isError ? (
        <p className="text-sm text-accent-coral">
          Non riesco a caricare le richieste.
        </p>
      ) : !pendingQ.data || pendingQ.data.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-text-muted">
            Nessuna richiesta in attesa. 🌿
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {pendingQ.data.map((p) => (
            <PendingCard
              key={p.id}
              pending={p}
              onApprove={() => approveM.mutate(p.id)}
              onReject={() => rejectM.mutate(p.id)}
              busy={approveM.isPending || rejectM.isPending}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function PendingCard({
  pending,
  onApprove,
  onReject,
  busy,
}: {
  pending: PendingApproval;
  onApprove: () => void;
  onReject: () => void;
  busy: boolean;
}) {
  const payload = pending.target_payload as
    | { list_title?: string; item_title?: string }
    | null;
  const itemTitle = payload?.item_title ?? `${pending.target_kind}#${pending.target_id}`;
  const listTitle = payload?.list_title ?? '';
  const expires = new Date(pending.expires_at);

  return (
    <li className="p-4 rounded-xl border border-accent-sun/40 bg-accent-sun/8 shadow-1">
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-md bg-accent-sun/20">
          <Lock size={18} className="text-accent-sun" />
        </div>
        <div className="flex-1">
          <p className="text-sm text-text-primary">
            <strong>{itemTitle}</strong>
            {listTitle && (
              <span className="text-text-muted">
                {' '}
                → lista <em>{listTitle}</em>
              </span>
            )}
          </p>
          <p className="text-xs text-text-muted mt-1">
            Richiesto da utente #{pending.requested_by_user_id} ·
            Scade {expires.toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}
          </p>
          <div className="flex gap-2 mt-3">
            <Button
              size="sm"
              leftIcon={<Check size={14} />}
              onClick={onApprove}
              disabled={busy}
            >
              Approva
            </Button>
            <Button
              size="sm"
              variant="ghost"
              leftIcon={<X size={14} />}
              onClick={onReject}
              disabled={busy}
            >
              Rifiuta
            </Button>
          </div>
        </div>
      </div>
    </li>
  );
}
