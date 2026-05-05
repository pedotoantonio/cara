// /me/memory — utente vede, edita, cancella e esporta i fatti che CARA
// ricorda di lui. Trasparenza totale + GDPR.

import { useEffect, useMemo, useState } from 'react';

import {
  Fact,
  createFact,
  deleteFact,
  exportMyMemory,
  listFacts,
  patchFact,
  purgeMyMemory,
} from '../api/memory';
import {
  Badge,
  BottomSheet,
  Button,
  Card,
  Field,
  IconButton,
  Input,
  cn,
  useToast,
} from '../design';

const FACT_TYPE_LABELS: Record<string, string> = {
  preference: 'Preferenza',
  allergy: 'Allergia',
  habit: 'Abitudine',
  relation: 'Relazione',
  schedule: 'Orario',
  personal: 'Personale',
  medical: 'Medico',
};

const FACT_TYPE_ORDER: string[] = [
  'allergy', 'medical', 'preference', 'habit',
  'schedule', 'relation', 'personal',
];

const SOURCE_LABEL: Record<string, string> = {
  explicit: 'tu hai detto',
  pattern:  'rilevato automaticamente',
  inferred: 'dedotto',
  pin:      'salvato manualmente',
};

const SOURCE_TONE: Record<string, 'accent' | 'ok' | 'celebrate' | 'muted'> = {
  explicit: 'ok',
  pin:      'accent',
  pattern:  'celebrate',
  inferred: 'muted',
};

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('it-IT', {
    day: '2-digit', month: 'short', year: 'numeric',
  });
}

export function MemoryPage() {
  const toast = useToast();

  const [facts, setFacts] = useState<Fact[] | null>(null);
  const [showInactive, setShowInactive] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState('');

  const [addOpen, setAddOpen] = useState(false);
  const [addText, setAddText] = useState('');
  const [addType, setAddType] = useState<string>('personal');
  const [addBusy, setAddBusy] = useState(false);

  const [purgeOpen, setPurgeOpen] = useState(false);
  const [purgeBusy, setPurgeBusy] = useState(false);

  async function refresh() {
    try {
      const rows = await listFacts({ activeOnly: !showInactive, limit: 300 });
      setFacts(rows);
    } catch (err) {
      console.error(err);
      toast.push({ kind: 'alert', title: 'Non riesco a caricare la memoria' });
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showInactive]);

  async function startEdit(f: Fact) {
    setEditingId(f.id);
    setEditText(f.text);
  }

  async function commitEdit() {
    if (editingId === null) return;
    const text = editText.trim();
    if (!text) { setEditingId(null); return; }
    try {
      const updated = await patchFact(editingId, { text });
      setFacts(cur => cur?.map(x => (x.id === editingId ? updated : x)) ?? null);
      toast.push({ kind: 'ok', title: 'Salvato' });
    } catch {
      toast.push({ kind: 'alert', title: 'Modifica fallita' });
    } finally {
      setEditingId(null);
    }
  }

  async function toggleActive(f: Fact) {
    try {
      const updated = await patchFact(f.id, { active: !f.active });
      setFacts(cur => cur?.map(x => (x.id === f.id ? updated : x)) ?? null);
    } catch {
      toast.push({ kind: 'alert', title: 'Aggiornamento fallito' });
    }
  }

  async function remove(f: Fact) {
    if (!confirm(`Cancellare "${f.text}"?`)) return;
    try {
      await deleteFact(f.id);
      setFacts(cur => cur?.map(x => x.id === f.id ? { ...x, active: false } : x) ?? null);
      toast.push({ kind: 'ok', title: 'Disattivato' });
    } catch {
      toast.push({ kind: 'alert', title: 'Cancellazione fallita' });
    }
  }

  async function add() {
    const t = addText.trim();
    if (!t || addBusy) return;
    setAddBusy(true);
    try {
      await createFact({ text: t, type: addType, confidence: 0.95 });
      toast.push({ kind: 'ok', title: 'Salvato' });
      setAddText('');
      setAddType('personal');
      setAddOpen(false);
      await refresh();
    } catch {
      toast.push({ kind: 'alert', title: 'Salvataggio fallito' });
    } finally {
      setAddBusy(false);
    }
  }

  async function exportJSON() {
    try {
      const blob = await exportMyMemory();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const date = new Date().toISOString().slice(0, 10);
      a.download = `cara-memoria-${date}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.push({ kind: 'celebrate', title: 'Esportazione scaricata' });
    } catch {
      toast.push({ kind: 'alert', title: 'Esportazione fallita' });
    }
  }

  async function commitPurge() {
    setPurgeBusy(true);
    try {
      const r = await purgeMyMemory();
      toast.push({
        kind: 'ok',
        title: 'Memoria cancellata',
        body: `${r.deleted} fatti rimossi.`,
      });
      setPurgeOpen(false);
      await refresh();
    } catch {
      toast.push({ kind: 'alert', title: 'Cancellazione fallita' });
    } finally {
      setPurgeBusy(false);
    }
  }

  // Group by type for clean display.
  const grouped = useMemo(() => {
    const out: Record<string, Fact[]> = {};
    for (const f of facts ?? []) {
      const key = f.type || 'personal';
      (out[key] ??= []).push(f);
    }
    return out;
  }, [facts]);

  const activeCount = facts?.filter(f => f.active).length ?? 0;
  const inactiveCount = facts?.filter(f => !f.active).length ?? 0;

  return (
    <div className="px-5 md:px-8 max-w-3xl mx-auto pb-8">
      <div className="flex items-end justify-between gap-3 mb-5">
        <div>
          <h1 className="font-display text-3xl md:text-4xl text-fg leading-tight">
            La tua memoria
          </h1>
          <p className="text-sm text-fg-soft mt-1">
            Quello che Cara ricorda di te. Puoi modificare, disattivare o
            cancellare ogni cosa.
          </p>
        </div>
        <Badge tone={activeCount > 0 ? 'accent' : 'muted'} dot>
          {activeCount} attivi
        </Badge>
      </div>

      {/* Actions row */}
      <div className="flex flex-wrap gap-2 mb-5">
        <Button
          variant="primary"
          size="sm"
          iconLeft="plus"
          onClick={() => setAddOpen(true)}
        >
          Aggiungi
        </Button>
        <Button
          variant="surface"
          size="sm"
          iconLeft="note"
          onClick={() => void exportJSON()}
        >
          Esporta JSON
        </Button>
        <Button
          variant="ghost"
          size="sm"
          iconLeft="trash"
          onClick={() => setPurgeOpen(true)}
          className="text-alert hover:text-alert"
        >
          Cancella tutto
        </Button>
        {inactiveCount > 0 && (
          <label className="ml-auto inline-flex items-center gap-2 text-xs text-fg-muted self-center cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={e => setShowInactive(e.target.checked)}
              className="accent-accent w-4 h-4"
            />
            Mostra disattivati ({inactiveCount})
          </label>
        )}
      </div>

      {/* Empty state */}
      {facts !== null && facts.length === 0 && (
        <Card variant="outline" className="text-center py-10 text-sm text-fg-muted">
          Cara non ricorda ancora nulla di te.
          <br />
          Dille "ricorda che…" oppure aggiungi un fatto qui sopra.
        </Card>
      )}

      {/* Loading */}
      {facts === null && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} variant="flat" padded className="animate-breathe h-16" />
          ))}
        </div>
      )}

      {/* Grouped list */}
      {facts !== null && facts.length > 0 && FACT_TYPE_ORDER
        .filter(t => grouped[t]?.length)
        .map(typeKey => (
          <div key={typeKey} className="mb-5">
            <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2 px-1">
              {FACT_TYPE_LABELS[typeKey] ?? typeKey}
            </h2>
            <div className="space-y-1.5">
              {grouped[typeKey].map(f => {
                const isEditing = editingId === f.id;
                return (
                  <div
                    key={f.id}
                    className={cn(
                      'group flex items-center gap-3 rounded-xl px-3 py-2.5 transition-all',
                      f.active
                        ? 'bg-surface1 ring-1 ring-fg/8 hover:bg-surface2'
                        : 'bg-surface1/60 text-fg-muted',
                    )}
                  >
                    <div className="flex-1 min-w-0">
                      {isEditing ? (
                        <input
                          autoFocus
                          value={editText}
                          onChange={e => setEditText(e.target.value)}
                          onBlur={commitEdit}
                          onKeyDown={e => {
                            if (e.key === 'Enter') { e.preventDefault(); void commitEdit(); }
                            else if (e.key === 'Escape') setEditingId(null);
                          }}
                          maxLength={500}
                          className="w-full bg-bg ring-1 ring-accent rounded-md px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
                        />
                      ) : (
                        <button
                          type="button"
                          onClick={() => f.active && startEdit(f)}
                          disabled={!f.active}
                          className={cn(
                            'block w-full text-left text-sm leading-snug',
                            !f.active && 'cursor-default line-through',
                            f.active && 'cursor-text hover:text-accent-dark',
                          )}
                          title={f.active ? 'Tocca per modificare' : 'Disattivato'}
                        >
                          {f.text}
                        </button>
                      )}
                      <div className="flex items-center gap-2 mt-1 text-2xs">
                        <Badge tone={SOURCE_TONE[f.source] ?? 'muted'} size="sm">
                          {SOURCE_LABEL[f.source] ?? f.source}
                        </Badge>
                        <span className="text-fg-muted">
                          {fmtDate(f.first_seen)}
                          {f.confidence < 1 && ` · sicurezza ${Math.round(f.confidence * 100)}%`}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-0.5 shrink-0">
                      <IconButton
                        name={f.active ? 'check' : 'plus'}
                        label={f.active ? 'Disattiva' : 'Riattiva'}
                        size="sm"
                        variant="plain"
                        onClick={() => toggleActive(f)}
                        className={f.active ? 'text-ok' : 'text-fg-muted'}
                      />
                      <IconButton
                        name="trash"
                        label="Elimina"
                        size="sm"
                        variant="plain"
                        onClick={() => void remove(f)}
                        className="text-fg-muted hover:!text-alert"
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}

      {/* Add sheet */}
      <BottomSheet
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Nuovo fatto"
        subtitle="Cosa vuoi che Cara ricordi di te?"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setAddOpen(false)}>
              Annulla
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={addBusy}
              disabled={!addText.trim()}
              onClick={() => void add()}
            >
              Salva
            </Button>
          </div>
        }
      >
        <div className="space-y-4 pb-2">
          <Field label="Fatto">
            <Input
              value={addText}
              onChange={e => setAddText(e.target.value)}
              placeholder="Es. Sono allergico ai pomodori"
              maxLength={500}
              autoFocus
            />
          </Field>
          <Field label="Tipo" hint="Aiuta Cara a recuperare il fatto al momento giusto.">
            <select
              value={addType}
              onChange={e => setAddType(e.target.value)}
              className="w-full h-11 rounded-lg bg-surface1 ring-1 ring-fg/8 px-3 text-fg focus:outline-none focus:ring-2 focus:ring-accent"
            >
              {FACT_TYPE_ORDER.map(k => (
                <option key={k} value={k}>{FACT_TYPE_LABELS[k]}</option>
              ))}
            </select>
          </Field>
        </div>
      </BottomSheet>

      {/* Purge confirmation */}
      <BottomSheet
        open={purgeOpen}
        onClose={() => setPurgeOpen(false)}
        title="Cancellare TUTTA la tua memoria?"
        subtitle="Questa è la procedura GDPR di rimozione. Niente undo."
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setPurgeOpen(false)}>
              Annulla
            </Button>
            <Button
              variant="alert"
              size="sm"
              iconLeft="trash"
              loading={purgeBusy}
              onClick={() => void commitPurge()}
            >
              Sì, cancella tutto
            </Button>
          </div>
        }
      >
        <Card variant="outline" tint="alert" className="!p-3 mb-3">
          <p className="text-sm text-fg leading-relaxed">
            Verranno eliminati definitivamente {activeCount + inactiveCount} fatti.
            I fatti familiari (condivisi con tutti) <strong>non</strong> sono toccati.
          </p>
        </Card>
        <p className="text-xs text-fg-muted">
          Suggerimento: prima di cancellare, scarica un backup con il bottone
          "Esporta JSON".
        </p>
      </BottomSheet>
    </div>
  );
}
