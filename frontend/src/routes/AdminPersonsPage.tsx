/**
 * Admin "Persone" page — lista volti noti, gestione, sezione sconosciuti.
 *
 * Backed by `/api/v1/admin/persons` which proxies frigate-faces under
 * the CARA auth + audit layer. Images are fetched same-origin via
 * `/api/v1/admin/persons/{id}/photo` so the browser doesn't have to
 * accept the cert on a second port (`:8452`) — that crossport setup
 * caused image loads to silently fail in some browsers.
 */

import { useEffect, useState } from 'react';

import { authFetch } from '../api/auth';
import {
  Person,
  UnknownSighting,
  assignSighting,
  createPerson,
  createPersonFromSighting,
  deletePerson,
  listPersons,
  listUnknowns,
  updatePerson,
  uploadPhoto,
} from '../api/persons';
import { Card, Icon, cn } from '../design';

/** Fetches an authenticated image and turns it into an object URL the
 *  <img> tag can load. <img src> can't carry the Bearer header, so we
 *  pull bytes via authFetch then expose them via createObjectURL. The
 *  URL is revoked on unmount so we don't leak blobs. */
function AuthedImage({
  endpoint,
  alt,
  className,
  fallback,
}: {
  endpoint: string;
  alt: string;
  className?: string;
  fallback?: React.ReactNode;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let revoked = false;
    let url: string | null = null;
    (async () => {
      try {
        const r = await authFetch(endpoint);
        if (!r.ok) { setFailed(true); return; }
        const blob = await r.blob();
        url = URL.createObjectURL(blob);
        if (!revoked) setSrc(url);
      } catch {
        setFailed(true);
      }
    })();
    return () => {
      revoked = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [endpoint]);

  if (failed || !src) {
    return <>{fallback ?? <div className={cn('bg-surface2', className)} />}</>;
  }
  return <img src={src} alt={alt} className={className} />;
}

function relTime(iso: string | null): string {
  if (!iso) return 'mai';
  const t = new Date(iso).getTime();
  if (!t) return 'mai';
  const min = Math.round((Date.now() - t) / 60_000);
  if (min < 1) return 'adesso';
  if (min < 60) return `${min} min fa`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h}h fa`;
  return `${Math.round(h / 24)}g fa`;
}

export function AdminPersonsPage() {
  const [people, setPeople] = useState<Person[] | null>(null);
  const [unknowns, setUnknowns] = useState<UnknownSighting[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [p, u] = await Promise.all([listPersons(), listUnknowns(50)]);
      setPeople(p);
      setUnknowns(u);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { void refresh(); }, []);

  return (
    <main className="px-4 md:px-8 py-6 max-w-5xl mx-auto space-y-6 pb-24">
      <header className="flex items-center justify-between">
        <h1 className="font-display text-2xl text-fg">Persone</h1>
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="inline-flex items-center gap-2 rounded-pill bg-accent text-bg px-4 py-2 text-sm font-medium"
        >
          <Icon name="plus" size={16} /> Aggiungi persona
        </button>
      </header>

      {error && (
        <Card variant="outline" tint="alert">
          <p className="text-sm text-alert">⚠ {error}</p>
        </Card>
      )}

      {loading && people === null && (
        <p className="text-sm text-fg-muted">Carico…</p>
      )}

      {people && people.length === 0 && (
        <Card>
          <p className="text-sm text-fg-muted">
            Nessuna persona catalogata. Tocca "Aggiungi persona" per
            iniziare, oppure assegna uno degli sconosciuti qui sotto.
          </p>
        </Card>
      )}

      {people && people.length > 0 && (
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {people.map((p) => (
            <PersonCard key={p.id} person={p} onChange={refresh} />
          ))}
        </section>
      )}

      <section>
        <h2 className="font-display text-lg text-fg mb-3">
          Sconosciuti recenti
          {unknowns && (
            <span className="ml-2 text-sm text-fg-muted">
              ({unknowns.length})
            </span>
          )}
        </h2>
        {unknowns && unknowns.length === 0 && (
          <p className="text-sm text-fg-muted">Nessun avvistamento non identificato.</p>
        )}
        {unknowns && unknowns.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {unknowns.map((u) => (
              <UnknownCard
                key={u.id}
                sighting={u}
                people={people ?? []}
                onChange={refresh}
              />
            ))}
          </div>
        )}
      </section>

      {showAdd && (
        <AddPersonModal
          onClose={() => setShowAdd(false)}
          onCreated={() => { setShowAdd(false); void refresh(); }}
        />
      )}
    </main>
  );
}

// ── PersonCard ─────────────────────────────────────────────────────────

function PersonCard({ person, onChange }: { person: Person; onChange: () => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(person.name);
  const [notify, setNotify] = useState(person.notify);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const photoUrl = person.latest_image
    ? `/api/v1/admin/persons/${person.id}/photo`
    : null;

  async function save() {
    setBusy(true); setErr(null);
    try {
      await updatePerson(person.id, { name, notify });
      setEditing(false);
      onChange();
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!confirm(`Eliminare definitivamente "${person.name}"?`)) return;
    setBusy(true); setErr(null);
    try { await deletePerson(person.id); onChange(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }
  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]; if (!f) return;
    setBusy(true); setErr(null);
    try { await uploadPhoto(person.id, f); onChange(); }
    catch (er) { setErr((er as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <Card>
      <div className="flex items-start gap-3">
        {photoUrl ? (
          <AuthedImage
            endpoint={photoUrl}
            alt={person.name}
            className="w-16 h-16 rounded-md object-cover bg-surface2"
            fallback={
              <div className="w-16 h-16 rounded-md bg-surface2 flex items-center justify-center">
                <Icon name="profile" size={28} className="text-fg-muted" />
              </div>
            }
          />
        ) : (
          <div className="w-16 h-16 rounded-md bg-surface2 flex items-center justify-center">
            <Icon name="profile" size={28} className="text-fg-muted" />
          </div>
        )}
        <div className="flex-1 min-w-0">
          {editing ? (
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full text-md font-medium bg-surface2 rounded-md px-2 py-1 mb-1"
            />
          ) : (
            <p className="text-md font-medium truncate">{person.name}</p>
          )}
          <p className="text-2xs text-fg-muted">
            {person.sighting_count} avvistamenti · ultimo {relTime(person.last_seen)}
          </p>
          <label className="inline-flex items-center gap-1.5 mt-2 text-xs text-fg-soft cursor-pointer">
            <input
              type="checkbox"
              checked={notify}
              onChange={(e) => setNotify(e.target.checked)}
              disabled={!editing && person.notify === notify}
              onClick={(e) => { if (!editing) e.preventDefault(); }}
            />
            Notifiche all'arrivo
          </label>
        </div>
      </div>

      {err && <p className="text-2xs text-alert mt-2">⚠ {err}</p>}

      <div className="flex gap-2 mt-3 flex-wrap">
        {editing ? (
          <>
            <button type="button" onClick={save} disabled={busy}
              className="text-xs rounded-pill bg-accent text-bg px-3 py-1.5">
              Salva
            </button>
            <button type="button" onClick={() => { setEditing(false); setName(person.name); setNotify(person.notify); }}
              className="text-xs text-fg-muted px-3 py-1.5">
              Annulla
            </button>
          </>
        ) : (
          <>
            <button type="button" onClick={() => setEditing(true)}
              className="text-xs rounded-pill bg-surface2 px-3 py-1.5">
              Modifica
            </button>
            <label className={cn(
              'text-xs rounded-pill bg-surface2 px-3 py-1.5 cursor-pointer',
              busy && 'opacity-50 pointer-events-none',
            )}>
              + Foto
              <input type="file" accept="image/*" className="hidden" onChange={upload} />
            </label>
            <button type="button" onClick={remove} disabled={busy}
              className="text-xs text-alert px-3 py-1.5 ml-auto">
              Elimina
            </button>
          </>
        )}
      </div>
    </Card>
  );
}

// ── UnknownCard ────────────────────────────────────────────────────────

function UnknownCard({
  sighting, people, onChange,
}: {
  sighting: UnknownSighting;
  people: Person[];
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const photoUrl = sighting.image_url
    ? `/api/v1/admin/persons/unknowns/${sighting.id}/image`
    : null;

  async function assign(personId: number) {
    setBusy(true); setErr(null);
    try { await assignSighting(sighting.id, personId); onChange(); }
    catch (e) { setErr((e as Error).message); setBusy(false); }
  }
  async function createNew() {
    if (!newName.trim()) return;
    setBusy(true); setErr(null);
    try {
      await createPersonFromSighting(sighting.id, newName.trim());
      onChange();
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  }

  return (
    <Card padded={false}>
      {photoUrl ? (
        <AuthedImage
          endpoint={photoUrl}
          alt=""
          className="w-full h-32 object-cover bg-surface2 rounded-t-md"
          fallback={
            <div className="w-full h-32 bg-surface2 rounded-t-md flex items-center justify-center">
              <Icon name="profile" size={28} className="text-fg-muted" />
            </div>
          }
        />
      ) : (
        <div className="w-full h-32 bg-surface2 rounded-t-md flex items-center justify-center">
          <Icon name="profile" size={28} className="text-fg-muted" />
        </div>
      )}
      <div className="p-3 space-y-2">
        <p className="text-2xs text-fg-muted">
          {sighting.camera ?? '?'} · {relTime(sighting.timestamp)}
        </p>
        {creating ? (
          <div className="flex gap-1">
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Nome"
              className="flex-1 text-xs bg-surface2 rounded-md px-2 py-1"
            />
            <button type="button" onClick={createNew} disabled={busy || !newName.trim()}
              className="text-xs rounded-pill bg-accent text-bg px-2 py-1">
              ✓
            </button>
            <button type="button" onClick={() => setCreating(false)}
              className="text-xs text-fg-muted px-2 py-1">
              ✕
            </button>
          </div>
        ) : (
          <select
            disabled={busy}
            className="w-full text-xs bg-surface2 rounded-md px-2 py-1"
            onChange={(e) => {
              const v = e.target.value;
              if (v === '__new__') { setCreating(true); }
              else if (v) void assign(parseInt(v, 10));
              e.currentTarget.value = '';
            }}
            defaultValue=""
          >
            <option value="" disabled>Assegna a…</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
            <option value="__new__">+ Nuova persona</option>
          </select>
        )}
        {err && <p className="text-2xs text-alert">⚠ {err}</p>}
      </div>
    </Card>
  );
}

// ── AddPersonModal ─────────────────────────────────────────────────────

function AddPersonModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('');
  const [notify, setNotify] = useState(true);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    if (!name.trim()) { setErr('Nome obbligatorio'); return; }
    setBusy(true); setErr(null);
    try {
      const created = await createPerson(name.trim(), notify);
      for (const f of files) {
        try { await uploadPhoto(created.id, f); } catch { /* continue */ }
      }
      onCreated();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-bg rounded-lg max-w-md w-full p-5 space-y-3" onClick={(e) => e.stopPropagation()}>
        <h2 className="font-display text-lg">Nuova persona</h2>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Nome"
          className="w-full text-md bg-surface2 rounded-md px-3 py-2"
        />
        <label className="inline-flex items-center gap-2 text-sm">
          <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} />
          Notifiche all'arrivo
        </label>
        <div>
          <label className="block text-xs text-fg-muted mb-1">Foto (1-5 immagini frontali)</label>
          <input
            type="file"
            accept="image/*"
            multiple
            onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, 5))}
            className="text-sm"
          />
          {files.length > 0 && (
            <p className="text-2xs text-fg-muted mt-1">{files.length} file selezionati</p>
          )}
        </div>
        {err && <p className="text-xs text-alert">⚠ {err}</p>}
        <div className="flex gap-2 justify-end pt-2">
          <button type="button" onClick={onClose} className="text-sm text-fg-muted px-3 py-1.5">
            Annulla
          </button>
          <button type="button" onClick={submit} disabled={busy || !name.trim()}
            className="text-sm rounded-pill bg-accent text-bg px-4 py-1.5 disabled:opacity-40">
            {busy ? 'Salvo…' : 'Crea'}
          </button>
        </div>
      </div>
    </div>
  );
}
