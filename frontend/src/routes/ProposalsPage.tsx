// /me/proposte — proposte di task estratte dalle email Gmail.
// L'utente accetta o ignora; Cara impara dai rifiuti.

import { useEffect, useState } from 'react';

import {
  Proposal,
  acceptProposal,
  listProposals,
  rejectProposal,
} from '../api/integrations';
import {
  Badge,
  Button,
  Card,
  CardSubtitle,
  CardTitle,
  Icon,
  cn,
  useToast,
} from '../design';
import { onFamilyEventPrefix } from '../lib/familySync';


function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return 'data non specificata';
  const d = new Date(iso);
  return d.toLocaleString('it-IT', {
    weekday: 'short', day: '2-digit', month: 'short',
    hour: '2-digit', minute: '2-digit',
  });
}


const TYPE_LABELS: Record<string, { label: string; tone: 'accent' | 'celebrate' | 'ok'; icon: 'task' | 'calendar' | 'budget' }> = {
  appointment:    { label: 'Appuntamento',  tone: 'accent',    icon: 'calendar' },
  task:           { label: 'Task',          tone: 'ok',        icon: 'task' },
  bill_reminder:  { label: 'Bolletta',      tone: 'celebrate', icon: 'budget' },
};


export function ProposalsPage() {
  const toast = useToast();
  const [proposals, setProposals] = useState<Proposal[] | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [showRejected, setShowRejected] = useState(false);

  async function refresh() {
    try {
      setProposals(await listProposals(showRejected ? 'rejected' : 'pending'));
    } catch {
      toast.push({ kind: 'alert', title: 'Proposte non disponibili' });
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showRejected]);

  // Re-fetch on family-bus event when the scanner writes new proposals.
  useEffect(() => {
    return onFamilyEventPrefix('email.proposal.', () => { void refresh(); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showRejected]);

  async function accept(p: Proposal) {
    setBusyId(p.id);
    try {
      const r = await acceptProposal(p.id);
      toast.push({
        kind: 'celebrate',
        title: 'Task creato',
        body: p.proposal_args.title,
      });
      setProposals(cur => cur?.filter(x => x.id !== p.id) ?? null);
      void r;
    } catch {
      toast.push({ kind: 'alert', title: 'Operazione fallita' });
    } finally {
      setBusyId(null);
    }
  }

  async function reject(p: Proposal) {
    setBusyId(p.id);
    try {
      await rejectProposal(p.id);
      setProposals(cur => cur?.filter(x => x.id !== p.id) ?? null);
      toast.push({ kind: 'info', title: 'Ignorato' });
    } catch {
      toast.push({ kind: 'alert', title: 'Operazione fallita' });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="px-5 md:px-8 max-w-3xl mx-auto pb-8">
      <div className="mb-5">
        <h1 className="font-display text-3xl md:text-4xl text-fg leading-tight">
          Proposte da email
        </h1>
        <p className="text-sm text-fg-soft mt-1">
          Cara legge le tue email e propone qui gli impegni che riconosce.
          Niente viene aggiunto senza la tua conferma.
        </p>
      </div>

      <div className="flex items-center gap-3 mb-4">
        <button
          type="button"
          onClick={() => setShowRejected(false)}
          className={cn(
            'text-xs rounded-pill px-3 py-1.5 transition-all',
            !showRejected ? 'bg-accent text-ivory shadow-warm' : 'bg-surface1 text-fg-soft',
          )}
        >
          In attesa
        </button>
        <button
          type="button"
          onClick={() => setShowRejected(true)}
          className={cn(
            'text-xs rounded-pill px-3 py-1.5 transition-all',
            showRejected ? 'bg-accent text-ivory shadow-warm' : 'bg-surface1 text-fg-soft',
          )}
        >
          Storia ignorate
        </button>
      </div>

      {proposals === null && (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i} variant="flat" className="animate-breathe h-28" />
          ))}
        </div>
      )}

      {proposals !== null && proposals.length === 0 && (
        <Card variant="outline" className="text-center py-10 text-sm text-fg-muted">
          {showRejected
            ? 'Nessuna proposta ignorata.'
            : 'Nessuna proposta in sospeso. Cara non ha trovato nuovi impegni nelle email recenti.'}
        </Card>
      )}

      {proposals !== null && proposals.map(p => {
        const meta = TYPE_LABELS[p.proposal_type] ?? TYPE_LABELS.task;
        const args = p.proposal_args;
        return (
          <Card key={p.id} variant="raised" className="mb-3">
            <div className="flex items-start gap-3 mb-2">
              <span className="h-9 w-9 rounded-pill bg-accent/15 text-accent flex items-center justify-center shrink-0">
                <Icon name={meta.icon} size={18} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <CardTitle className="!text-base !leading-tight">
                    {args.title || p.subject || 'Promemoria'}
                  </CardTitle>
                  <Badge tone={meta.tone} size="sm">{meta.label}</Badge>
                  <Badge tone="muted" size="sm">
                    {Math.round(p.confidence * 100)}%
                  </Badge>
                  {p.source_layer === 'cloud_llm' && (
                    <Badge tone="celebrate" size="sm">cloud</Badge>
                  )}
                </div>
                {p.from_address && (
                  <CardSubtitle className="!mt-1 truncate">
                    da {p.from_address}
                  </CardSubtitle>
                )}
              </div>
            </div>

            <div className="ml-12 text-sm text-fg space-y-1">
              {args.due_date && (
                <div className="flex items-center gap-2">
                  <Icon name="calendar" size={14} className="text-fg-muted shrink-0" />
                  {fmtWhen(args.due_date)}
                </div>
              )}
              {args.location && (
                <div className="flex items-center gap-2">
                  <Icon name="home" size={14} className="text-fg-muted shrink-0" />
                  {args.location}
                </div>
              )}
              {p.snippet && (
                <p className="text-xs text-fg-muted italic mt-2 line-clamp-2">
                  "{p.snippet}"
                </p>
              )}
            </div>

            {!showRejected && (
              <div className="mt-3 flex justify-end gap-2">
                <Button
                  variant="ghost" size="sm" iconLeft="close"
                  onClick={() => void reject(p)}
                  disabled={busyId === p.id}
                >
                  Ignora
                </Button>
                <Button
                  variant="primary" size="sm" iconLeft="check"
                  onClick={() => void accept(p)}
                  loading={busyId === p.id}
                >
                  Crea task
                </Button>
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
