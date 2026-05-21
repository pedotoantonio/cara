// /admin/persona — admin governance of per-user persona profiles.
// List users → click → see markdown + sections, rebuild, edit, delete.

import { useEffect, useState } from 'react';

import {
  PersonaProfile,
  adminDeletePersona,
  adminGetPersona,
  adminPatchPersona,
  adminRebuildPersona,
} from '../api/persona';
import { listUsers, type User } from '../api/users';
import { Badge, Button, Card, CardSubtitle, CardTitle, useToast } from '../design';

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('it-IT', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function statusBadge(status: string | null | undefined) {
  if (!status) return <Badge tone="muted">Mai costruito</Badge>;
  if (status === 'ok') return <Badge tone="ok">OK</Badge>;
  if (status === 'low_confidence') return <Badge tone="accent">Bassa confidenza</Badge>;
  if (status === 'failed') return <Badge tone="alert">Errore</Badge>;
  if (status === 'skipped_no_messages') return <Badge tone="muted">Niente di nuovo</Badge>;
  return <Badge tone="muted">{status}</Badge>;
}

export function AdminPersonaPage() {
  const toast = useToast();
  const [users, setUsers] = useState<User[] | null>(null);
  const [selected, setSelected] = useState<User | null>(null);
  const [profile, setProfile] = useState<PersonaProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editMd, setEditMd] = useState('');
  const [editConf, setEditConf] = useState<string>('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        setUsers(await listUsers());
      } catch {
        toast.push({ kind: 'alert', title: 'Utenti non disponibili' });
      }
    })();
  }, [toast]);

  async function loadProfile(u: User) {
    setSelected(u);
    setProfile(null);
    setEditing(false);
    setLoading(true);
    try {
      const p = await adminGetPersona(u.id);
      setProfile(p);
      setEditMd(p?.markdown ?? '');
      setEditConf(p?.confidence != null ? String(p.confidence) : '');
    } catch {
      toast.push({ kind: 'alert', title: 'Profilo non disponibile' });
    } finally {
      setLoading(false);
    }
  }

  async function rebuild() {
    if (!selected) return;
    if (
      !confirm(
        `Ricostruire il profilo di ${selected.full_name || selected.email}?\n\n`
          + `Può richiedere 1-3 minuti (passa attraverso il modello).`,
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      const result = await adminRebuildPersona(selected.id);
      toast.push({
        kind: 'ok',
        title: `Ricostruito (${result.status})`,
        body: `${result.chunks_processed ?? 0} chunk · confidenza ${result.confidence ?? '?'}%`,
      });
      await loadProfile(selected);
    } catch (e) {
      toast.push({ kind: 'alert', title: 'Rebuild fallito', body: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function savePatch() {
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await adminPatchPersona(selected.id, {
        markdown: editMd,
        confidence: editConf ? parseFloat(editConf) : null,
      });
      setProfile(updated);
      setEditing(false);
      toast.push({ kind: 'ok', title: 'Profilo aggiornato' });
    } catch (e) {
      toast.push({ kind: 'alert', title: 'Patch fallita', body: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function deleteProfile() {
    if (!selected) return;
    if (!confirm(`Cancellare il profilo di ${selected.full_name || selected.email}?`)) return;
    setBusy(true);
    try {
      await adminDeletePersona(selected.id);
      setProfile(null);
      toast.push({ kind: 'ok', title: 'Profilo cancellato' });
    } catch (e) {
      toast.push({ kind: 'alert', title: 'Delete fallita', body: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex-1 overflow-y-auto bg-slate-900 text-slate-100">
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        <header>
          <h1 className="text-xl font-medium">Profili Persona</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Profilo longitudinale per-utente, costruito di notte (03:15) via map-reduce LLM.
            Iniettato nel system prompt di CARA per dare coerenza tra le conversazioni.
          </p>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-4">
          {/* User list */}
          <aside className="rounded-2xl bg-slate-800/60 border border-slate-700 p-3 space-y-1">
            {users === null && (
              <p className="text-xs text-slate-500 p-2">Carico utenti…</p>
            )}
            {users?.map((u) => (
              <button
                key={u.id}
                onClick={() => loadProfile(u)}
                className={`w-full text-left rounded-xl px-3 py-2 text-sm transition ${
                  selected?.id === u.id
                    ? 'bg-emerald-600/30 border border-emerald-500/40'
                    : 'hover:bg-slate-700/40'
                }`}
              >
                <div className="font-medium">{u.full_name || u.email.split('@')[0]}</div>
                <div className="text-[11px] text-slate-400">{u.role} · {u.email}</div>
              </button>
            ))}
            {users?.length === 0 && (
              <p className="text-xs text-slate-500 p-2">Nessun utente.</p>
            )}
          </aside>

          {/* Profile view */}
          <section className="space-y-4">
            {!selected && (
              <Card>
                <CardTitle>Seleziona un utente</CardTitle>
                <CardSubtitle>per vedere il suo profilo.</CardSubtitle>
              </Card>
            )}

            {selected && loading && (
              <Card>
                <CardTitle>Carico…</CardTitle>
              </Card>
            )}

            {selected && !loading && !profile && (
              <Card>
                <CardTitle>Nessun profilo</CardTitle>
                <CardSubtitle>
                  {selected.full_name || selected.email} non ha ancora un profilo materializzato.
                </CardSubtitle>
                <div className="mt-4 flex gap-2">
                  <Button onClick={rebuild} disabled={busy}>
                    {busy ? 'Costruisco…' : 'Costruisci ora'}
                  </Button>
                </div>
              </Card>
            )}

            {selected && profile && (
              <>
                <Card>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <CardTitle>{selected.full_name || selected.email}</CardTitle>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                        {statusBadge(profile.last_status)}
                        <span>Confidenza: <b>{profile.confidence ?? '?'}%</b></span>
                        <span>·</span>
                        <span>Costruito: {fmtDate(profile.last_built_at)}</span>
                        <span>·</span>
                        <span>{profile.markdown.length} caratteri</span>
                      </div>
                      {profile.last_error && (
                        <p className="mt-2 text-xs text-rose-400">
                          Ultimo errore: {profile.last_error}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-col gap-2">
                      <Button onClick={rebuild} disabled={busy} variant="primary">
                        {busy ? '…' : 'Rebuild'}
                      </Button>
                      <Button
                        onClick={() => setEditing((v) => !v)}
                        variant="ghost"
                        disabled={busy}
                      >
                        {editing ? 'Annulla' : 'Modifica'}
                      </Button>
                      <Button onClick={deleteProfile} variant="ghost" disabled={busy}>
                        Elimina
                      </Button>
                    </div>
                  </div>
                </Card>

                {editing ? (
                  <Card>
                    <CardTitle>Modifica manuale</CardTitle>
                    <CardSubtitle>
                      Override del Markdown. La prossima ricostruzione notturna farà MERGE con
                      questo testo.
                    </CardSubtitle>
                    <div className="mt-3 space-y-3">
                      <textarea
                        value={editMd}
                        onChange={(e) => setEditMd(e.target.value)}
                        rows={20}
                        className="w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                      />
                      <div className="flex items-center gap-3">
                        <label className="text-xs text-slate-400">Confidenza %</label>
                        <input
                          type="number"
                          min={0}
                          max={100}
                          value={editConf}
                          onChange={(e) => setEditConf(e.target.value)}
                          className="w-20 rounded-xl bg-slate-900 border border-slate-700 px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                        />
                        <Button onClick={savePatch} disabled={busy} variant="primary">
                          Salva override
                        </Button>
                      </div>
                    </div>
                  </Card>
                ) : (
                  <Card>
                    <CardTitle>Profilo (Markdown)</CardTitle>
                    <pre className="mt-2 whitespace-pre-wrap break-words text-xs text-slate-300 leading-relaxed">
                      {profile.markdown || '(vuoto)'}
                    </pre>
                  </Card>
                )}

                {profile.sections && Object.keys(profile.sections).length > 0 && (
                  <Card>
                    <CardTitle>Sezioni (parsate)</CardTitle>
                    <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                      {Object.entries(profile.sections).map(([name, sec]) => (
                        <div key={name} className="rounded-xl bg-slate-900/60 border border-slate-700 p-3">
                          <h3 className="text-sm font-medium mb-2">{name}</h3>
                          {sec.stable.length > 0 && (
                            <ul className="mb-2 space-y-1 text-xs text-slate-300">
                              {sec.stable.map((s, i) => (
                                <li key={i}>
                                  <span className="text-emerald-400 mr-1">●</span>
                                  {s}
                                </li>
                              ))}
                            </ul>
                          )}
                          {sec.episodic.length > 0 && (
                            <ul className="space-y-1 text-xs text-slate-400 italic">
                              {sec.episodic.map((e, i) => (
                                <li key={i}>
                                  <span className="text-amber-400 mr-1">○</span>
                                  {e.date && <span className="mr-1">[{e.date}]</span>}
                                  {e.text}
                                </li>
                              ))}
                            </ul>
                          )}
                          {sec.stable.length === 0 && sec.episodic.length === 0 && (
                            <p className="text-xs text-slate-500">Vuoto</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </Card>
                )}
              </>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
