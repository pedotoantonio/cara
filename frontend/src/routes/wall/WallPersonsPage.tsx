// Family face management for the Wall — LAN-only, no auth.
//
// Three sections, top to bottom:
//   1. "Presenta una persona" — name input + multi-photo upload, creates
//      the person in frigate-faces and uploads each picture as a
//      reference face.
//   2. Known people grid — for every registered person: latest photo,
//      sighting count, rename / +foto / notify toggle / delete.
//   3. Unknown sightings — recent unrecognised faces. For each, the
//      user can either assign to an existing person (dropdown) or
//      create a new one inline (name input).
//
// All mutations write an audit row server-side under actor "wall".

import { useEffect, useRef, useState } from 'react';

import {
  assignWallUnknown,
  createWallPerson,
  createWallPersonFromUnknown,
  deleteWallPerson,
  fetchWallPersons,
  fetchWallUnknowns,
  patchWallPerson,
  probeWallPersonImage,
  uploadWallPersonPhoto,
  wallPersonPhotoUrl,
  wallUnknownImageUrl,
} from '../../api/wall';
import type { WallPerson, WallProbeResult, WallUnknown } from '../../api/wall';

export function WallPersonsPage() {
  const [persons, setPersons] = useState<WallPerson[]>([]);
  const [unknowns, setUnknowns] = useState<WallUnknown[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [thumbBust, setThumbBust] = useState<number>(Date.now());

  async function refresh() {
    try {
      const [p, u] = await Promise.all([fetchWallPersons(), fetchWallUnknowns(50)]);
      setPersons(p);
      setUnknowns(u);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    const id = window.setInterval(refresh, 30_000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function withBusy<T>(key: string, fn: () => Promise<T>): Promise<T | null> {
    setBusy((b) => ({ ...b, [key]: true }));
    try {
      return await fn();
    } catch (e) {
      setError((e as Error).message);
      return null;
    } finally {
      setBusy((b) => ({ ...b, [key]: false }));
    }
  }

  // ── Section 1: introduce a new person ──────────────────────────
  const [newName, setNewName] = useState('');
  const [newFiles, setNewFiles] = useState<File[]>([]);
  const newFileInputRef = useRef<HTMLInputElement | null>(null);
  // Duplicate-suggest modal state. We only fire the probe when the
  // user is about to create a NEW person — adding photos to an
  // existing one already implies "I know who this is".
  const [probeMatch, setProbeMatch] = useState<WallProbeResult['match'] | null>(null);
  const [probing, setProbing] = useState(false);

  async function uploadAllTo(personId: number) {
    for (const f of newFiles) {
      await uploadWallPersonPhoto(personId, f);
    }
    setNewName('');
    setNewFiles([]);
    if (newFileInputRef.current) newFileInputRef.current.value = '';
    setThumbBust(Date.now());
    setProbeMatch(null);
    await refresh();
  }

  async function handleCreate() {
    const name = newName.trim();
    if (!name) {
      setError('Inserisci un nome');
      return;
    }
    if (newFiles.length === 0) {
      setError('Carica almeno una foto');
      return;
    }
    // 1. Probe the FIRST photo against the catalogue before creating
    //    a new person. If frigate-faces returns a match (distance ≤
    //    MATCH_TOLERANCE 0.55), open the confirm modal so the user
    //    can decide: upload to the existing person, or proceed with
    //    a new one anyway.
    setProbing(true);
    let probe: WallProbeResult | null = null;
    try {
      probe = await probeWallPersonImage(newFiles[0]);
    } catch (e) {
      // If the probe fails (e.g. no face detected, frigate-faces down)
      // we don't block the user — fall back to the original flow and
      // let the actual upload give a clean error if there's a problem.
      probe = null;
    } finally {
      setProbing(false);
    }
    if (probe?.match && probe.match.person_id) {
      setProbeMatch(probe.match);
      return; // wait for the user's modal decision
    }
    await proceedAsNewPerson();
  }

  async function proceedAsNewPerson() {
    const name = newName.trim();
    await withBusy('create', async () => {
      const p = await createWallPerson(name, true);
      await uploadAllTo(p.id);
    });
  }

  async function confirmAsExistingPerson(personId: number) {
    setProbeMatch(null);
    await withBusy('create', async () => {
      // No create_person; the existing record is reused — just append
      // every photo as a new reference (each one strengthens the
      // recognizer for that person).
      await uploadAllTo(personId);
    });
  }

  // ── Section 3: assign unknown to existing or create new ────────
  const [assignTo, setAssignTo] = useState<Record<number, string>>({});
  const [newFromUnknown, setNewFromUnknown] = useState<Record<number, string>>({});

  async function handleAssign(sightingId: number) {
    const target = assignTo[sightingId];
    if (!target) return;
    await withBusy(`assign:${sightingId}`, async () => {
      await assignWallUnknown(sightingId, parseInt(target, 10));
      setAssignTo((m) => ({ ...m, [sightingId]: '' }));
      setThumbBust(Date.now());
      await refresh();
    });
  }

  async function handleCreateFromUnknown(sightingId: number) {
    const name = (newFromUnknown[sightingId] || '').trim();
    if (!name) return;
    await withBusy(`create-from:${sightingId}`, async () => {
      await createWallPersonFromUnknown(sightingId, name, true);
      setNewFromUnknown((m) => ({ ...m, [sightingId]: '' }));
      setThumbBust(Date.now());
      await refresh();
    });
  }

  // ── Section 2 actions ─────────────────────────────────────────
  async function handleAddPhotos(personId: number, files: FileList | null) {
    if (!files || files.length === 0) return;
    await withBusy(`upload:${personId}`, async () => {
      for (const f of Array.from(files)) {
        await uploadWallPersonPhoto(personId, f);
      }
      setThumbBust(Date.now());
      await refresh();
    });
  }

  async function handleRename(personId: number, current: string) {
    const next = window.prompt('Nuovo nome', current)?.trim();
    if (!next || next === current) return;
    await withBusy(`rename:${personId}`, async () => {
      await patchWallPerson(personId, { name: next });
      await refresh();
    });
  }

  async function handleToggleNotify(p: WallPerson) {
    await withBusy(`notify:${p.id}`, async () => {
      await patchWallPerson(p.id, { notify: !p.notify });
      await refresh();
    });
  }

  async function handleDelete(p: WallPerson) {
    if (!window.confirm(`Eliminare ${p.name}? I volti registrati andranno persi.`)) return;
    await withBusy(`delete:${p.id}`, async () => {
      await deleteWallPerson(p.id);
      await refresh();
    });
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4 space-y-6">
      <header className="flex items-baseline justify-between">
        <h2 className="text-2xl font-semibold tracking-tight">Famiglia · Riconoscimento volti</h2>
        <div className="text-sm text-fg-muted">
          {persons.length} persone · {unknowns.length} sconosciuti recenti
        </div>
      </header>

      {error && (
        <div className="rounded-md bg-rose-500/10 ring-1 ring-rose-500/30 px-3 py-2 text-rose-300 text-sm flex justify-between items-start gap-3">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="opacity-70 hover:opacity-100">×</button>
        </div>
      )}

      {/* ── Section 1: introduce someone new ─────────────────── */}
      <section className="rounded-xl bg-bg-elevated/60 ring-1 ring-white/5 p-4 space-y-3">
        <div>
          <h3 className="font-medium">Presenta una persona a CARA</h3>
          <p className="text-xs text-fg-muted mt-0.5">
            Inserisci nome e carica 1–5 foto del viso (frontale, ben illuminato).
            CARA imparerà a riconoscerlo dalle telecamere di casa.
          </p>
        </div>
        <div className="flex flex-col md:flex-row gap-2">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Nome (es. Antonio)"
            className="flex-1 px-3 py-2 rounded-md bg-bg/60 ring-1 ring-white/10 text-sm focus:ring-accent focus:outline-none"
          />
          <input
            ref={newFileInputRef}
            type="file"
            accept="image/*"
            multiple
            onChange={(e) => setNewFiles(Array.from(e.target.files || []).slice(0, 5))}
            className="text-sm text-fg-muted file:mr-3 file:px-3 file:py-2 file:rounded-md file:border-0 file:bg-accent/20 file:text-fg hover:file:bg-accent/30 file:cursor-pointer"
          />
          <button
            onClick={handleCreate}
            disabled={busy.create || probing || !newName.trim() || newFiles.length === 0}
            className="px-4 py-2 rounded-md bg-emerald-600/30 hover:bg-emerald-600/50 disabled:opacity-30 disabled:cursor-not-allowed text-emerald-100 text-sm transition"
          >
            {probing ? 'Verifico…' : busy.create ? 'Caricamento…' : 'Presenta'}
          </button>
        </div>
        {newFiles.length > 0 && (
          <div className="text-xs text-fg-muted">
            {newFiles.length} foto pronte: {newFiles.map((f) => f.name).join(', ')}
          </div>
        )}
      </section>

      {/* ── Section 2: known people ───────────────────────────── */}
      <section className="space-y-3">
        <h3 className="font-medium">Persone conosciute</h3>
        {loading && persons.length === 0 ? (
          <div className="text-sm text-fg-muted">Caricamento…</div>
        ) : persons.length === 0 ? (
          <div className="text-sm text-fg-muted">
            Nessuno per ora. Presenta la prima persona con il modulo qui sopra.
          </div>
        ) : (
          <ul className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
            {persons.map((p) => (
              <li
                key={p.id}
                className="rounded-xl bg-bg-elevated/60 ring-1 ring-white/5 overflow-hidden flex flex-col"
              >
                <div className="aspect-square bg-bg/40 flex items-center justify-center overflow-hidden">
                  {p.latest_image ? (
                    <img
                      src={`${wallPersonPhotoUrl(p.id)}?t=${thumbBust}`}
                      alt={p.name}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <span className="text-fg-muted text-3xl">👤</span>
                  )}
                </div>
                <div className="p-3 flex flex-col gap-2">
                  <div>
                    <div className="font-medium truncate">{p.name}</div>
                    <div className="text-xs text-fg-muted">
                      {p.sighting_count} avvistament{p.sighting_count === 1 ? 'o' : 'i'}
                    </div>
                  </div>
                  <div className="flex gap-1.5 flex-wrap">
                    <label
                      className={`px-2 py-1 rounded-md text-xs cursor-pointer transition ${
                        busy[`upload:${p.id}`]
                          ? 'opacity-30 cursor-not-allowed'
                          : 'bg-accent/20 hover:bg-accent/30'
                      }`}
                    >
                      + foto
                      <input
                        type="file"
                        accept="image/*"
                        multiple
                        className="hidden"
                        disabled={busy[`upload:${p.id}`]}
                        onChange={(e) => {
                          handleAddPhotos(p.id, e.target.files);
                          e.target.value = '';
                        }}
                      />
                    </label>
                    <button
                      onClick={() => handleRename(p.id, p.name)}
                      className="px-2 py-1 rounded-md text-xs bg-zinc-700/40 hover:bg-zinc-700/60"
                    >
                      rinomina
                    </button>
                    <button
                      onClick={() => handleToggleNotify(p)}
                      className={`px-2 py-1 rounded-md text-xs ${
                        p.notify
                          ? 'bg-emerald-600/30 text-emerald-200'
                          : 'bg-zinc-700/40 text-fg-muted'
                      }`}
                      title={p.notify ? 'Notifica attiva' : 'Silenzioso'}
                    >
                      {p.notify ? '🔔' : '🔕'}
                    </button>
                    <button
                      onClick={() => handleDelete(p)}
                      className="px-2 py-1 rounded-md text-xs bg-rose-600/20 hover:bg-rose-600/40 text-rose-200"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── Probe-match confirm modal ─────────────────────────── */}
      {probeMatch && (
        <div
          className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => setProbeMatch(null)}
        >
          <div
            className="rounded-2xl bg-bg-elevated ring-1 ring-white/10 p-5 max-w-md w-full space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div>
              <h3 className="font-semibold text-lg">Forse è già conosciuta</h3>
              <p className="text-sm text-fg-muted mt-1">
                Questa foto somiglia a <span className="text-fg font-medium">{probeMatch.name}</span>{' '}
                (similarità {(1 - probeMatch.distance).toFixed(2)}).
                È la stessa persona o un'altra?
              </p>
              <p className="text-xs text-fg-muted mt-2">
                Se è {probeMatch.name}, le tue foto verranno aggiunte al suo archivio
                — niente duplicati. Se invece è qualcun altro, procediamo a creare
                una nuova persona "{newName.trim()}".
              </p>
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              <button
                onClick={() => confirmAsExistingPerson(probeMatch.person_id)}
                disabled={busy.create}
                className="flex-1 px-3 py-2 rounded-md bg-emerald-600/30 hover:bg-emerald-600/50 disabled:opacity-30 text-emerald-100 text-sm"
              >
                Sì, è {probeMatch.name}
              </button>
              <button
                onClick={() => { setProbeMatch(null); proceedAsNewPerson(); }}
                disabled={busy.create}
                className="flex-1 px-3 py-2 rounded-md bg-zinc-700/40 hover:bg-zinc-700/60 disabled:opacity-30 text-fg text-sm"
              >
                No, è una persona diversa
              </button>
            </div>
            <button
              onClick={() => setProbeMatch(null)}
              className="text-xs text-fg-muted hover:text-fg"
            >
              Annulla
            </button>
          </div>
        </div>
      )}

      {/* ── Section 3: unknown sightings ──────────────────────── */}
      <section className="space-y-3">
        <h3 className="font-medium">
          Volti sconosciuti recenti
        </h3>
        {unknowns.length === 0 ? (
          <div className="text-sm text-fg-muted">Nessun volto sconosciuto da assegnare.</div>
        ) : (
          <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {unknowns.map((u) => (
              <li
                key={u.id}
                className="rounded-xl bg-bg-elevated/60 ring-1 ring-white/5 overflow-hidden flex flex-col"
              >
                <div className="aspect-video bg-bg/40 flex items-center justify-center overflow-hidden">
                  <img
                    src={`${wallUnknownImageUrl(u.id)}?t=${thumbBust}`}
                    alt={`Sighting ${u.id}`}
                    className="w-full h-full object-cover"
                  />
                </div>
                <div className="p-3 flex flex-col gap-2 text-xs text-fg-muted">
                  <div className="flex justify-between gap-2">
                    <span>{u.camera || 'camera ?'}</span>
                    <span>{u.timestamp?.slice(11, 16) || '—'}</span>
                  </div>

                  <div className="flex gap-1.5">
                    <select
                      value={assignTo[u.id] || ''}
                      onChange={(e) => setAssignTo((m) => ({ ...m, [u.id]: e.target.value }))}
                      className="flex-1 px-2 py-1 rounded-md bg-bg/60 ring-1 ring-white/10 text-fg text-xs"
                      disabled={busy[`assign:${u.id}`]}
                    >
                      <option value="">Assegna a…</option>
                      {persons.map((p) => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                      ))}
                    </select>
                    <button
                      onClick={() => handleAssign(u.id)}
                      disabled={!assignTo[u.id] || busy[`assign:${u.id}`]}
                      className="px-2 py-1 rounded-md text-xs bg-emerald-600/30 hover:bg-emerald-600/50 disabled:opacity-30 disabled:cursor-not-allowed text-emerald-100"
                    >
                      OK
                    </button>
                  </div>

                  <div className="flex gap-1.5">
                    <input
                      type="text"
                      placeholder="oppure nuovo nome"
                      value={newFromUnknown[u.id] || ''}
                      onChange={(e) => setNewFromUnknown((m) => ({ ...m, [u.id]: e.target.value }))}
                      className="flex-1 px-2 py-1 rounded-md bg-bg/60 ring-1 ring-white/10 text-fg text-xs focus:ring-accent focus:outline-none"
                    />
                    <button
                      onClick={() => handleCreateFromUnknown(u.id)}
                      disabled={!newFromUnknown[u.id]?.trim() || busy[`create-from:${u.id}`]}
                      className="px-2 py-1 rounded-md text-xs bg-accent/30 hover:bg-accent/50 disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      Crea
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
