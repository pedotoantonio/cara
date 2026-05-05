// /admin/memory — admin governance della memoria di tutti gli utenti.
// Lista utenti con conteggi, click → vede e modera i fatti del singolo.

import { useEffect, useState } from 'react';

import {
  UserMemorySummary,
  deactivateUserFact,
  listUserFacts,
  listUsersWithFacts,
  purgeUserMemory,
} from '../api/adminMemory';
import { Fact } from '../api/memory';
import {
  Badge,
  BottomSheet,
  Button,
  Card,
  CardSubtitle,
  CardTitle,
  Icon,
  IconButton,
  cn,
  useToast,
} from '../design';

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('it-IT', {
    day: '2-digit', month: 'short', year: 'numeric',
  });
}

export function AdminMemoryPage() {
  const toast = useToast();
  const [users, setUsers] = useState<UserMemorySummary[] | null>(null);
  const [selected, setSelected] = useState<UserMemorySummary | null>(null);
  const [facts, setFacts] = useState<Fact[] | null>(null);
  const [showInactive, setShowInactive] = useState(true);

  const [purgeOpen, setPurgeOpen] = useState(false);
  const [purgeBusy, setPurgeBusy] = useState(false);

  async function refreshUsers() {
    try {
      setUsers(await listUsersWithFacts());
    } catch {
      toast.push({ kind: 'alert', title: 'Lista utenti non disponibile' });
    }
  }

  useEffect(() => { void refreshUsers(); }, []);

  async function openUser(u: UserMemorySummary) {
    setSelected(u);
    setFacts(null);
    try {
      setFacts(await listUserFacts(u.user_id, { activeOnly: !showInactive }));
    } catch {
      toast.push({ kind: 'alert', title: 'Fatti non disponibili' });
    }
  }

  useEffect(() => {
    if (selected) void openUser(selected);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showInactive]);

  async function deactivate(f: Fact) {
    if (!selected) return;
    if (!confirm(`Disattivare "${f.text}"?`)) return;
    try {
      await deactivateUserFact(selected.user_id, f.id);
      setFacts(cur => cur?.map(x => x.id === f.id ? { ...x, active: false } : x) ?? null);
      toast.push({ kind: 'ok', title: 'Disattivato' });
      await refreshUsers();
    } catch {
      toast.push({ kind: 'alert', title: 'Operazione fallita' });
    }
  }

  async function commitPurge() {
    if (!selected) return;
    setPurgeBusy(true);
    try {
      const r = await purgeUserMemory(selected.user_id);
      toast.push({
        kind: 'ok',
        title: 'Purge completato',
        body: `${r.deleted} fatti rimossi per ${selected.email}.`,
      });
      setPurgeOpen(false);
      setSelected(null);
      setFacts(null);
      await refreshUsers();
    } catch {
      toast.push({ kind: 'alert', title: 'Purge fallito' });
    } finally {
      setPurgeBusy(false);
    }
  }

  return (
    <div className="px-5 md:px-8 max-w-4xl mx-auto pb-8">
      <div className="mb-5">
        <h1 className="font-display text-3xl md:text-4xl text-fg leading-tight">
          Memoria · Admin
        </h1>
        <p className="text-sm text-fg-soft mt-1">
          Modera la memoria di ogni membro della famiglia. Le azioni qui sono
          tracciate nell'audit log.
        </p>
      </div>

      {users === null && (
        <Card variant="flat" className="animate-breathe h-24" />
      )}

      {users !== null && users.length === 0 && (
        <Card variant="outline" className="text-center py-10 text-sm text-fg-muted">
          Nessun utente con fatti.
        </Card>
      )}

      {users !== null && users.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {users.map(u => (
            <Card
              key={u.user_id}
              variant="raised"
              hoverable
              onClick={() => void openUser(u)}
              className="cursor-pointer"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <CardTitle className="!text-base truncate">
                    {u.full_name || u.email}
                  </CardTitle>
                  <CardSubtitle className="!mt-0.5 truncate">
                    {u.email}{u.role ? ` · ${u.role}` : ''}
                  </CardSubtitle>
                </div>
                <Icon name="profile" size={18} className="text-fg-muted shrink-0" />
              </div>
              <div className="mt-3 flex items-center gap-2">
                <Badge tone="accent" size="sm" dot>
                  {u.facts_active} attivi
                </Badge>
                {u.facts_total > u.facts_active && (
                  <Badge tone="muted" size="sm">
                    {u.facts_total - u.facts_active} disattivati
                  </Badge>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Per-user sheet */}
      <BottomSheet
        open={selected !== null}
        onClose={() => { setSelected(null); setFacts(null); }}
        title={selected?.full_name || selected?.email || 'Memoria utente'}
        subtitle={selected ? `${selected.email}` : undefined}
        size="lg"
        footer={
          <div className="flex items-center justify-between gap-3">
            <Button
              variant="alert"
              size="sm"
              iconLeft="trash"
              onClick={() => setPurgeOpen(true)}
              disabled={!facts || facts.length === 0}
            >
              Purge tutto
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
              Chiudi
            </Button>
          </div>
        }
      >
        <div className="mb-3 flex items-center gap-3">
          <label className="inline-flex items-center gap-2 text-xs text-fg-muted cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={e => setShowInactive(e.target.checked)}
              className="accent-accent w-4 h-4"
            />
            Mostra disattivati
          </label>
        </div>

        {facts === null && (
          <Card variant="flat" className="animate-breathe h-20" />
        )}

        {facts !== null && facts.length === 0 && (
          <p className="text-sm text-fg-muted text-center py-6">
            Nessun fatto da mostrare.
          </p>
        )}

        {facts !== null && facts.length > 0 && (
          <div className="space-y-1.5">
            {facts.map(f => (
              <div
                key={f.id}
                className={cn(
                  'flex items-start gap-3 rounded-lg px-3 py-2.5',
                  f.active ? 'bg-surface1 ring-1 ring-fg/8' : 'bg-surface1/60 text-fg-muted',
                )}
              >
                <div className="flex-1 min-w-0">
                  <div className={cn('text-sm leading-snug', !f.active && 'line-through')}>
                    {f.text}
                  </div>
                  <div className="text-2xs text-fg-muted mt-1">
                    {f.type} · {f.source} · {fmtDate(f.first_seen)}
                  </div>
                </div>
                {f.active && (
                  <IconButton
                    name="trash"
                    label="Disattiva"
                    size="sm"
                    variant="plain"
                    onClick={() => void deactivate(f)}
                    className="text-fg-muted hover:!text-alert"
                  />
                )}
              </div>
            ))}
          </div>
        )}
      </BottomSheet>

      {/* Purge confirmation */}
      <BottomSheet
        open={purgeOpen}
        onClose={() => setPurgeOpen(false)}
        title="Purge totale memoria utente?"
        subtitle="Cancellazione definitiva. Niente undo. Verrà loggato in audit."
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
              Conferma purge
            </Button>
          </div>
        }
      >
        {selected && (
          <Card variant="outline" tint="alert" className="!p-3">
            <p className="text-sm text-fg leading-relaxed">
              Verranno eliminati <strong>{facts?.length ?? 0}</strong> fatti
              per <strong>{selected.email}</strong>. I fatti familiari
              (condivisi con tutti) <strong>non</strong> sono toccati.
            </p>
          </Card>
        )}
      </BottomSheet>
    </div>
  );
}
