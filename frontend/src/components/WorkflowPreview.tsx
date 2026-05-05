// Card che mostra la preview di un workflow (scontrino / bolletta / ricetta)
// PRIMA dell'esecuzione delle azioni proposte. L'utente conferma o annulla.
//
// Mostrata in chat quando l'utente carica una foto / PDF / link e il
// backend matcha un workflow concreto. Layout: header (workflow + confidence)
// + lista azioni proposte con azione+args + bottone "Conferma".

import { useState } from 'react';

import {
  ProposedAction,
  WorkflowRunResponse,
  runWorkflow,
} from '../api/workflows';
import { Badge, Button, Card, Icon, cn, useToast } from '../design';

interface Props {
  result: WorkflowRunResponse;
  /** Original input — needed to re-POST with confirmed=true. */
  rerunArgs: {
    text?: string;
    url?: string;
    ocr_text?: string;
    pdf_text?: string;
    image_b64?: string;
    pdf_b64?: string;
  };
  onConfirmed?: (resp: WorkflowRunResponse) => void;
  onCancelled?: () => void;
}

const WORKFLOW_LABELS: Record<string, { label: string; icon: 'shopping' | 'budget' | 'note' | 'spark' }> = {
  receipt: { label: 'Scontrino',   icon: 'shopping' },
  bill:    { label: 'Bolletta',    icon: 'budget' },
  recipe:  { label: 'Ricetta',     icon: 'note' },
};


function summariseStructured(structured: Record<string, unknown> | null): string[] {
  if (!structured) return [];
  const out: string[] = [];

  // Receipt
  if ('total_cents' in structured && typeof structured.total_cents === 'number') {
    out.push(`Totale: € ${(structured.total_cents / 100).toFixed(2)}`);
  }
  if ('vendor' in structured && structured.vendor) {
    out.push(`Esercente: ${structured.vendor}`);
  }
  if ('date' in structured && structured.date) {
    out.push(`Data: ${structured.date}`);
  }
  if ('items' in structured && Array.isArray(structured.items)) {
    out.push(`${structured.items.length} articoli`);
  }

  // Bill
  if ('amount_cents' in structured && typeof structured.amount_cents === 'number') {
    out.push(`Importo: € ${(structured.amount_cents / 100).toFixed(2)}`);
  }
  if ('provider' in structured && structured.provider) {
    out.push(`Fornitore: ${structured.provider}`);
  }
  if ('due_date' in structured && structured.due_date) {
    out.push(`Scadenza: ${structured.due_date}`);
  }

  // Recipe
  if ('name' in structured && structured.name) {
    out.push(`Ricetta: ${structured.name}`);
  }
  if ('ingredients' in structured && Array.isArray(structured.ingredients)) {
    out.push(`${structured.ingredients.length} ingredienti`);
  }

  return out;
}


function formatActionArgs(action: ProposedAction): string {
  const a = action.args;
  if (action.tool === 'add_shopping' && 'title' in a) {
    return String(a.title);
  }
  if (action.tool === 'add_task' && 'title' in a) {
    return String(a.title);
  }
  if (action.tool === 'add_expense') {
    const amt = typeof a.amount_cents === 'number'
      ? `€ ${(a.amount_cents / 100).toFixed(2)}`
      : '';
    const cat = a.category ? ` · ${a.category}` : '';
    return `${amt}${cat}`.trim();
  }
  // Generic fallback.
  return Object.entries(a)
    .filter(([k]) => k !== 'user_id')
    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
    .join(', ')
    .slice(0, 120);
}


export function WorkflowPreview({ result, rerunArgs, onConfirmed, onCancelled }: Props) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(result.executed);

  if (!result.matched || !result.workflow_name) return null;

  const meta = WORKFLOW_LABELS[result.workflow_name] ?? {
    label: result.workflow_name,
    icon: 'spark' as const,
  };
  const summary = summariseStructured(result.structured);

  async function confirm() {
    if (busy) return;
    setBusy(true);
    try {
      const resp = await runWorkflow({ ...rerunArgs, confirmed: true });
      setDone(true);
      toast.push({
        kind: 'celebrate',
        title: 'Eseguito',
        body: `${resp.execution_results.length} azioni applicate.`,
      });
      onConfirmed?.(resp);
    } catch (e) {
      toast.push({
        kind: 'alert',
        title: 'Esecuzione fallita',
        body: (e as Error).message,
      });
    } finally {
      setBusy(false);
    }
  }

  function cancel() {
    onCancelled?.();
    toast.push({ kind: 'info', title: 'Annullato' });
  }

  return (
    <Card variant="raised" tint="accent" className="my-3">
      <div className="flex items-start gap-3 mb-3">
        <span className="h-9 w-9 rounded-pill bg-accent/15 text-accent flex items-center justify-center shrink-0">
          <Icon name={meta.icon} size={18} />
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-display text-md text-fg">{meta.label}</h3>
            {result.confidence !== null && (
              <Badge tone="muted" size="sm">
                {Math.round((result.confidence ?? 0) * 100)}%
              </Badge>
            )}
            {done && <Badge tone="ok" size="sm" dot>eseguito</Badge>}
          </div>
          {summary.length > 0 && (
            <p className="text-xs text-fg-soft mt-1">
              {summary.join(' · ')}
            </p>
          )}
        </div>
      </div>

      {result.proposed_actions.length > 0 && !done && (
        <>
          <div className="text-2xs uppercase tracking-wider text-fg-muted mb-1.5">
            Azioni proposte
          </div>
          <ul className="space-y-1.5 mb-3">
            {result.proposed_actions.map((a, i) => (
              <li
                key={`${a.signature}-${i}`}
                className={cn(
                  'flex items-start gap-2 rounded-md px-2.5 py-1.5 text-xs',
                  'bg-bg ring-1 ring-fg/8',
                )}
              >
                <Icon
                  name={a.reversible ? 'check' : 'bell'}
                  size={13}
                  className={cn(
                    'mt-0.5 shrink-0',
                    a.reversible ? 'text-ok' : 'text-celebrate',
                  )}
                />
                <div className="min-w-0 flex-1">
                  <div className="font-mono text-2xs text-fg-muted">{a.tool}</div>
                  <div className="text-fg leading-snug">
                    {a.summary || formatActionArgs(a)}
                  </div>
                  {a.auto_confirmable && (
                    <div className="text-2xs text-celebrate mt-0.5">
                      Cara la farà automaticamente da ora in poi
                    </div>
                  )}
                  {!a.auto_confirmable && a.confirms_remaining > 0 && (
                    <div className="text-2xs text-fg-muted mt-0.5">
                      {a.confirms_remaining} conferme alla auto-conferma
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {done ? (
        <div className="text-xs text-ok">
          ✓ Tutte le azioni sono state applicate.
        </div>
      ) : (
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={cancel}>
            Non applicare
          </Button>
          <Button
            variant="primary"
            size="sm"
            iconLeft="check"
            loading={busy}
            onClick={() => void confirm()}
          >
            Conferma
          </Button>
        </div>
      )}
    </Card>
  );
}
