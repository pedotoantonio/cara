import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import {
  ArrowLeft,
  EnvelopeSimple,
  Check,
  X as XIcon,
} from '@phosphor-icons/react';
import {
  Button,
  Card,
  CardSubtitle,
  CardTitle,
  Skeleton,
  Badge,
  useToast,
} from '@/design/components';
import { useAvatarStore } from '@/state/avatar';
import { listProposals, acceptProposal, rejectProposal, type EmailProposal } from '@/api/proposals';

export function ProposalsPage() {
  const navigate = useNavigate();
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  const toast = useToast();
  const queryClient = useQueryClient();

  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'thoughtful',
      glowAccent: 'clay',
      caption: null,
      context: 'me:proposals',
    });
  }, [setAvatar]);

  const q = useQuery({
    queryKey: ['proposals'],
    queryFn: listProposals,
    staleTime: 60_000,
  });

  const acceptM = useMutation({
    mutationFn: (id: number) => acceptProposal(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ['proposals'] });
      const prev = queryClient.getQueryData<EmailProposal[]>(['proposals']);
      queryClient.setQueryData<EmailProposal[]>(['proposals'], (p) =>
        p ? p.filter((x) => x.id !== id) : p,
      );
      return { prev };
    },
    onSuccess: () => {
      toast.push({ tone: 'mint', title: 'Accettata' });
      void queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
    onError: (err, _id, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['proposals'], ctx.prev);
      toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message });
    },
  });

  const rejectM = useMutation({
    mutationFn: (id: number) => rejectProposal(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ['proposals'] });
      const prev = queryClient.getQueryData<EmailProposal[]>(['proposals']);
      queryClient.setQueryData<EmailProposal[]>(['proposals'], (p) =>
        p ? p.filter((x) => x.id !== id) : p,
      );
      return { prev };
    },
    onError: (err, _id, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['proposals'], ctx.prev);
      toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message });
    },
  });

  const items = (q.data ?? []).filter((p) => p.status === 'pending');

  return (
    <div className="container-app py-4 space-y-4">
      <header className="flex items-center gap-2">
        <button onClick={() => navigate('/me')} className="p-2 -m-2" aria-label="Indietro">
          <ArrowLeft size={20} />
        </button>
        <h1 className="font-display text-2xl">Proposte da email</h1>
      </header>

      <Card padding="base" surface="surface" elevation={0}>
        <div className="flex items-start gap-3">
          <EnvelopeSimple size={24} weight="duotone" className="text-accent-clay" />
          <CardSubtitle>
            Task che ho estratto dalle tue email Gmail. Conferma quelli che vuoi davvero
            tenere — gli altri li scarto.
          </CardSubtitle>
        </div>
      </Card>

      {q.isLoading && (
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      )}

      {!q.isLoading && items.length === 0 && (
        <p className="text-text-muted text-center py-8 text-sm">
          Nessuna proposta in attesa. Tutto a posto.
        </p>
      )}

      <ul className="space-y-2">
        <AnimatePresence>
          {items.map((p) => (
            <motion.li
              key={p.id}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, x: 60 }}
            >
              <Card padding="lg" elevation={1}>
                <div className="flex items-start gap-2 mb-2">
                  <Badge tone="clay" size="sm">
                    {p.kind}
                  </Badge>
                  {p.source && (
                    <Badge tone="neutral" size="sm">
                      {p.source}
                    </Badge>
                  )}
                </div>
                <CardTitle>{p.title}</CardTitle>
                {p.body && (
                  <p className="text-sm text-text-secondary mt-1 line-clamp-3">{p.body}</p>
                )}
                {p.email_subject && (
                  <CardSubtitle className="mt-2">
                    da email: "{p.email_subject}"
                    {p.email_from && <span> · {p.email_from}</span>}
                  </CardSubtitle>
                )}
                <div className="mt-3 flex gap-2">
                  <Button
                    size="sm"
                    variant="primary"
                    leftIcon={<Check size={14} />}
                    onClick={() => acceptM.mutate(p.id)}
                    loading={acceptM.isPending}
                  >
                    Aggiungi alle task
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    leftIcon={<XIcon size={14} />}
                    onClick={() => rejectM.mutate(p.id)}
                    loading={rejectM.isPending}
                  >
                    Scarta
                  </Button>
                </div>
              </Card>
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
    </div>
  );
}
