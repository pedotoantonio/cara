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
  cleanupAllPersonImages,
  createWallPerson,
  createWallPersonFromUnknown,
  deleteWallPerson,
  fetchPersonReadiness,
  fetchWallPersons,
  fetchWallUnknowns,
  patchWallPerson,
  probeWallPersonImage,
  uploadWallPersonPhoto,
  wallPersonPhotoUrl,
  wallUnknownImageUrl,
} from '../../api/wall';
import type {
  PersonReadiness,
  ReadinessPair,
  WallPerson,
  WallProbeResult,
  WallUnknown,
} from '../../api/wall';

export function WallPersonsPage() {
  const [persons, setPersons] = useState<WallPerson[]>([]);
  const [unknowns, setUnknowns] = useState<WallUnknown[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [thumbBust, setThumbBust] = useState<number>(Date.now());
  const [readiness, setReadiness] = useState<Record<number, PersonReadiness>>({});
  const [openReadiness, setOpenReadiness] = useState<PersonReadiness | null>(null);

  async function refresh() {
    try {
      const [p, u] = await Promise.all([fetchWallPersons(), fetchWallUnknowns(50)]);
      setPersons(p);
      setUnknowns(u);
      setError(null);
      // Fan out readiness fetches in parallel; one failure doesn't
      // stall the others. Fast (~50 ms each) on the typical 1-5
      // person catalogue; we don't gate the page render on it.
      void Promise.all(
        p.map(async (person) => {
          try {
            const r = await fetchPersonReadiness(person.id);
            setReadiness((prev) => ({ ...prev, [person.id]: r }));
          } catch {/* leave entry unset; pill renders as `…` */}
        }),
      );
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
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-medium">Persone conosciute</h3>
          <DiskCleanupButton onDone={refresh} />
        </div>
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
                  <ReadinessPill
                    readiness={readiness[p.id] ?? null}
                    onClick={() => readiness[p.id] && setOpenReadiness(readiness[p.id])}
                  />
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

      {openReadiness && (
        <ReadinessModal
          readiness={openReadiness}
          onClose={() => setOpenReadiness(null)}
        />
      )}
    </div>
  );
}


// ─── Readiness UI ──────────────────────────────────────────────────

function readinessTone(score: number): {
  bg: string; ring: string; text: string;
} {
  if (score >= 95) return {
    bg: 'bg-emerald-500/15', ring: 'ring-emerald-500/40', text: 'text-emerald-300',
  };
  if (score >= 80) return {
    bg: 'bg-sky-500/15', ring: 'ring-sky-500/40', text: 'text-sky-300',
  };
  if (score >= 60) return {
    bg: 'bg-amber-500/15', ring: 'ring-amber-500/40', text: 'text-amber-300',
  };
  return {
    bg: 'bg-rose-500/15', ring: 'ring-rose-500/40', text: 'text-rose-300',
  };
}

function ReadinessPill({
  readiness, onClick,
}: { readiness: PersonReadiness | null; onClick: () => void }) {
  if (!readiness) {
    return (
      <div className="px-2 py-1 rounded-md text-xs bg-bg/60 text-fg-muted ring-1 ring-white/5 text-center">
        Calcolo riconoscimento…
      </div>
    );
  }
  const tone = readinessTone(readiness.overall);
  const icon =
    readiness.overall >= 95 ? '🎯'
    : readiness.overall >= 80 ? '✓'
    : readiness.overall >= 60 ? '◐'
    : '!';
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-2 py-1.5 rounded-md text-xs ring-1 transition cursor-pointer hover:brightness-125 ${tone.bg} ${tone.ring} ${tone.text}`}
      title="Apri dettagli riconoscimento"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono font-semibold">
          {icon} {readiness.overall}%
        </span>
        <span className="text-[10px] opacity-80">
          {readiness.metrics.reference_count} foto
        </span>
      </div>
      <div className="text-[10px] opacity-90 mt-0.5 truncate">
        {readiness.verdict}
      </div>
    </button>
  );
}

function ReadinessModal({
  readiness, onClose,
}: { readiness: PersonReadiness; onClose: () => void }) {
  const tone = readinessTone(readiness.overall);
  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="rounded-2xl bg-bg-elevated ring-1 ring-white/10 p-6 max-w-lg w-full space-y-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-fg-muted text-xs uppercase tracking-wide">
              Riconoscimento facciale
            </div>
            <div className="text-xl font-semibold">{readiness.name}</div>
          </div>
          <button
            onClick={onClose}
            className="px-2 py-1 text-fg-muted hover:text-fg"
            aria-label="Chiudi"
          >
            ✕
          </button>
        </div>

        {/* Big overall gauge */}
        <div className={`rounded-xl ${tone.bg} ring-1 ${tone.ring} px-5 py-4 flex items-center gap-4`}>
          <div className="relative w-20 h-20 shrink-0">
            <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
              <circle
                cx="18" cy="18" r="15.9155"
                fill="none" stroke="currentColor" strokeOpacity="0.2"
                strokeWidth="3"
              />
              <circle
                cx="18" cy="18" r="15.9155"
                fill="none" stroke="currentColor"
                strokeWidth="3" strokeLinecap="round"
                strokeDasharray={`${readiness.overall} 100`}
                className={tone.text}
              />
            </svg>
            <div className={`absolute inset-0 flex items-center justify-center font-mono font-bold text-lg ${tone.text}`}>
              {readiness.overall}%
            </div>
          </div>
          <div>
            <div className={`font-medium ${tone.text}`}>{readiness.verdict}</div>
            <div className="text-xs text-fg-muted mt-1">
              {readiness.metrics.reference_count} foto di riferimento
              {readiness.metrics.sampled_for_pairs < readiness.metrics.reference_count &&
                ` · ${readiness.metrics.sampled_for_pairs} campionate per la diversità`}
            </div>
          </div>
        </div>

        {/* Sub-scores */}
        <div className="grid grid-cols-3 gap-2">
          <SubScoreCell
            label="Copertura"
            score={readiness.scores.coverage}
            hint="quante foto"
          />
          <SubScoreCell
            label="Diversità"
            score={readiness.scores.diversity}
            hint="varietà angoli/luce"
          />
          <SubScoreCell
            label="Distinzione"
            score={readiness.scores.discriminability}
            hint="vs altre persone"
          />
        </div>

        {/* Per-pair distinguishability */}
        <div className="space-y-2">
          <div className="text-fg-muted text-xs uppercase tracking-wide">
            Distinzione vs altri membri
          </div>
          <PairwiseList pairs={readiness.pairs} />
        </div>

        {/* Suggestions */}
        {readiness.suggestions.length > 0 && (
          <div className="space-y-2">
            <div className="text-fg-muted text-xs uppercase tracking-wide">
              Per migliorare
            </div>
            {readiness.suggestions.map((s, i) => (
              <div
                key={i}
                className={`rounded-lg px-3 py-2 text-sm ring-1 ${
                  s.priority === 'high'
                    ? 'bg-amber-500/10 ring-amber-500/30 text-amber-100'
                    : s.priority === 'medium'
                      ? 'bg-sky-500/10 ring-sky-500/30 text-sky-100'
                      : 'bg-emerald-500/10 ring-emerald-500/30 text-emerald-100'
                }`}
              >
                <div className="font-medium">{s.text}</div>
                {s.detail && (
                  <div className="text-xs opacity-80 mt-0.5">{s.detail}</div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Raw metrics — small + dev-friendly */}
        <details className="text-xs text-fg-muted">
          <summary className="cursor-pointer hover:text-fg">
            Dettagli numerici
          </summary>
          <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 font-mono">
            <dt className="opacity-70">tolleranza match</dt>
            <dd>{readiness.metrics.match_tolerance.toFixed(2)}</dd>
            {readiness.metrics.intra_mean_distance !== null && (
              <>
                <dt className="opacity-70">distanza media intra-classe</dt>
                <dd>{readiness.metrics.intra_mean_distance.toFixed(3)}</dd>
              </>
            )}
            {readiness.metrics.intra_max_distance !== null && (
              <>
                <dt className="opacity-70">distanza max intra-classe</dt>
                <dd>{readiness.metrics.intra_max_distance.toFixed(3)}</dd>
              </>
            )}
            {readiness.metrics.closest_other_distance !== null && (
              <>
                <dt className="opacity-70">
                  distanza min vs {readiness.metrics.closest_other_name ?? '—'}
                </dt>
                <dd>{readiness.metrics.closest_other_distance.toFixed(3)}</dd>
              </>
            )}
          </dl>
        </details>
      </div>
    </div>
  );
}

function fmtBytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}

function DiskCleanupButton({ onDone }: { onDone: () => Promise<void> | void }) {
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setReport(null);
    try {
      // First a dry-run so we can warn the user what will go.
      const dry = await cleanupAllPersonImages(1, true);
      if (dry.total_deleted === 0) {
        setReport('Niente da liberare.');
        setTimeout(() => setReport(null), 3000);
        return;
      }
      const ok = window.confirm(
        `Liberare ${fmtBytes(dry.total_bytes_freed)} eliminando ${dry.total_deleted} file (uno per persona resta come miniatura)?\n\n` +
        `Gli encoding facciali restano: il riconoscimento NON peggiora.`,
      );
      if (!ok) return;
      const real = await cleanupAllPersonImages(1, false);
      setReport(
        `${real.total_deleted} file rimossi · liberati ${fmtBytes(real.total_bytes_freed)}`,
      );
      await onDone();
      setTimeout(() => setReport(null), 6000);
    } catch (e) {
      setReport(`Errore: ${(e as Error).message}`);
      setTimeout(() => setReport(null), 6000);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      {report && (
        <span className="text-xs text-fg-muted italic">{report}</span>
      )}
      <button
        onClick={run}
        disabled={busy}
        className="px-3 py-1 rounded-md text-xs bg-zinc-700/40 hover:bg-zinc-700/60 disabled:opacity-30"
        title="Cancella le foto vecchie già encodificate. Mantiene una miniatura per persona."
      >
        {busy ? 'Pulisco…' : '🧹 Libera spazio'}
      </button>
    </div>
  );
}

function SubScoreCell({
  label, score, hint,
}: { label: string; score: number | null; hint: string }) {
  if (score === null) {
    return (
      <div className="rounded-lg bg-bg/40 ring-1 ring-white/5 px-3 py-2">
        <div className="font-mono font-semibold text-fg-muted">n/d</div>
        <div className="text-fg text-xs mt-0.5">{label}</div>
        <div className="text-fg-muted text-[10px]">{hint}</div>
      </div>
    );
  }
  const tone = readinessTone(score);
  return (
    <div className={`rounded-lg ${tone.bg} ring-1 ${tone.ring} px-3 py-2`}>
      <div className={`font-mono font-semibold ${tone.text}`}>{score}%</div>
      <div className="text-fg text-xs mt-0.5">{label}</div>
      <div className="text-fg-muted text-[10px]">{hint}</div>
    </div>
  );
}

function PairwiseList({ pairs }: { pairs: ReadinessPair[] }) {
  if (pairs.length === 0) {
    return (
      <div className="rounded-lg bg-bg/40 ring-1 ring-white/5 px-3 py-2 text-xs text-fg-muted">
        Sei l'unica persona iscritta — la distinzione fra membri della
        famiglia diventa misurabile quando ne aggiungi un'altra.
      </div>
    );
  }
  return (
    <ul className="space-y-1.5">
      {pairs.map((p) => {
        const tone = readinessTone(p.confidence_pct);
        return (
          <li
            key={p.other_id}
            className={`flex items-center justify-between gap-3 rounded-md ${tone.bg} ring-1 ${tone.ring} px-3 py-1.5`}
          >
            <div className="min-w-0">
              <div className="text-sm truncate">vs <span className="font-medium">{p.other_name}</span></div>
              <div className="text-[10px] text-fg-muted font-mono">
                distanza {p.min_distance.toFixed(2)} · {p.verdict}
              </div>
            </div>
            <div className={`font-mono font-semibold text-sm ${tone.text}`}>
              {p.confidence_pct}%
            </div>
          </li>
        );
      })}
    </ul>
  );
}
