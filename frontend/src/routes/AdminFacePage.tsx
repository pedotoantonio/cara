/**
 * /admin/face — admin governance for the face recognition feature.
 *
 * Three sections:
 *   1. Global settings (kill switch, default threshold, opt-in models)
 *   2. Profiles table (rename, retune threshold, toggle child/active,
 *      delete with double-confirmation)
 *   3. Stats summary (total profiles, descriptors, identifications)
 *
 * All operations go through the Phase 1/2 REST surface and inherit its
 * audit logging on the backend.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import {
  deleteFaceProfile,
  getFaceSettings,
  listFaceProfiles,
  updateFaceProfile,
  updateFaceSettings,
} from '../api/face';
import { Badge, Button, Card, CardSubtitle, CardTitle, IconButton, cn, useToast } from '../design';
import type { FaceProfile, FaceSettings } from '../features/face/types';


function fmtDate(iso: string | null): string {
  if (!iso) return 'mai';
  const d = new Date(iso);
  return d.toLocaleString('it-IT', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}


export function AdminFacePage() {
  const toast = useToast();
  const navigate = useNavigate();

  const [profiles, setProfiles] = useState<FaceProfile[]>([]);
  const [settings, setSettings] = useState<FaceSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<FaceProfile | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [pl, s] = await Promise.all([listFaceProfiles(), getFaceSettings()]);
      setProfiles(pl);
      setSettings(s);
    } catch (err) {
      toast.push({
        kind: 'alert',
        title: 'Caricamento fallito',
        body: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onSettingsChange = useCallback(
    async (patch: Partial<FaceSettings>) => {
      if (!settings) return;
      try {
        const updated = await updateFaceSettings(patch);
        setSettings(updated);
        toast.push({ kind: 'ok', title: 'Impostazioni aggiornate' });
      } catch (err) {
        toast.push({
          kind: 'alert',
          title: 'Aggiornamento fallito',
          body: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [settings, toast],
  );

  const onDelete = useCallback(
    async (id: string) => {
      try {
        await deleteFaceProfile(id);
        toast.push({ kind: 'ok', title: 'Profilo eliminato' });
        setPendingDelete(null);
        await refresh();
      } catch (err) {
        toast.push({
          kind: 'alert',
          title: 'Eliminazione fallita',
          body: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [refresh, toast],
  );

  const totals = useMemo(() => {
    let descriptors = 0;
    let recognitions = 0;
    for (const p of profiles) {
      descriptors += p.descriptorCount;
      recognitions += p.recognitionCount;
    }
    return { profiles: profiles.length, descriptors, recognitions };
  }, [profiles]);

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 py-6 space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Riconoscimento facciale</h1>
          <p className="text-sm text-slate-500">
            Profili enrolled, soglie di match e impostazioni globali.
          </p>
        </div>
        <Button onClick={() => navigate('/face/enroll')} variant="primary" iconLeft="plus">
          Registra nuovo volto
        </Button>
      </header>

      <StatsRow totals={totals} />

      <SettingsCard
        settings={settings}
        loading={loading && settings === null}
        onChange={onSettingsChange}
      />

      <Card>
        <CardTitle>Profili enrolled</CardTitle>
        <CardSubtitle>
          {profiles.length === 0
            ? 'Nessun profilo ancora registrato.'
            : `${profiles.length} ${profiles.length === 1 ? 'profilo' : 'profili'}`}
        </CardSubtitle>

        {loading && profiles.length === 0 ? (
          <p className="text-sm text-slate-500 mt-4">Caricamento…</p>
        ) : profiles.length === 0 ? (
          <div className="mt-4 rounded-lg border border-dashed border-slate-300 p-6 text-center">
            <p className="text-sm text-slate-600 mb-3">
              Nessuno è stato ancora registrato. Inizia col tuo profilo.
            </p>
            <Button onClick={() => navigate('/face/enroll')} variant="primary">
              Registra il primo volto
            </Button>
          </div>
        ) : (
          <ProfilesTable
            profiles={profiles}
            pendingDelete={pendingDelete}
            onEdit={setEditing}
            onRequestDelete={(id) => setPendingDelete(id)}
            onCancelDelete={() => setPendingDelete(null)}
            onConfirmDelete={onDelete}
          />
        )}
      </Card>

      {editing && (
        <EditProfileModal
          profile={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await refresh();
          }}
        />
      )}
    </div>
  );
}


// ─── Stats row ─────────────────────────────────────────────────────────


function StatsRow({
  totals,
}: {
  totals: { profiles: number; descriptors: number; recognitions: number };
}) {
  const stats = [
    { label: 'Profili', value: totals.profiles },
    { label: 'Descrittori', value: totals.descriptors },
    { label: 'Riconoscimenti', value: totals.recognitions },
  ];
  return (
    <div className="grid grid-cols-3 gap-3">
      {stats.map((s) => (
        <Card key={s.label}>
          <div className="text-3xl font-semibold tabular-nums">{s.value}</div>
          <div className="text-sm text-slate-500">{s.label}</div>
        </Card>
      ))}
    </div>
  );
}


// ─── Settings card ─────────────────────────────────────────────────────


function SettingsCard({
  settings,
  loading,
  onChange,
}: {
  settings: FaceSettings | null;
  loading: boolean;
  onChange: (patch: Partial<FaceSettings>) => void;
}) {
  if (loading || !settings) {
    return (
      <Card>
        <CardTitle>Impostazioni globali</CardTitle>
        <p className="text-sm text-slate-500 mt-4">Caricamento…</p>
      </Card>
    );
  }

  return (
    <Card>
      <CardTitle>Impostazioni globali</CardTitle>
      <CardSubtitle>
        Toggle generale + parametri di default. Si applicano a tutti i
        dispositivi.
      </CardSubtitle>

      <div className="mt-4 space-y-4">
        <SettingRow
          label="Riconoscimento attivo"
          description="Spegne tutte le pipeline di riconoscimento. Niente cattura webcam, niente match. CARA continua a funzionare."
        >
          <Toggle
            checked={settings.enabled}
            onChange={(v) => onChange({ enabled: v })}
          />
        </SettingRow>

        <SettingRow
          label="Soglia di match predefinita"
          description="Distanza euclidea sotto cui un volto è considerato 'lo stesso'. Più bassa = più stringente. Default 0.5."
        >
          <ThresholdSlider
            value={settings.defaultThreshold}
            onChange={(v) => onChange({ defaultThreshold: v })}
          />
        </SettingRow>

        <SettingRow
          label="Rilevazione espressioni"
          description="Carica anche faceExpressionNet (~330 KB) per stimare emozione. Usato dalla faccia di CARA per rispecchiare."
        >
          <Toggle
            checked={settings.expressionEnabled}
            onChange={(v) => onChange({ expressionEnabled: v })}
          />
        </SettingRow>

        <SettingRow
          label="Stima età e genere"
          description="Dati particolarmente sensibili. Lascia OFF se non hai motivi forti per attivarli, soprattutto se ci sono minori in casa."
        >
          <Toggle
            checked={settings.ageGenderEnabled}
            onChange={(v) => onChange({ ageGenderEnabled: v })}
          />
        </SettingRow>
      </div>
    </Card>
  );
}


function SettingRow({
  label,
  description,
  children,
}: {
  label: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 pb-4 last:pb-0 border-b last:border-b-0 border-slate-100">
      <div className="flex-1">
        <div className="font-medium">{label}</div>
        <div className="text-sm text-slate-500 mt-0.5 max-w-prose">{description}</div>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}


function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
        checked ? 'bg-emerald-500' : 'bg-slate-300',
      )}
    >
      <span
        className={cn(
          'inline-block h-5 w-5 rounded-full bg-white shadow transition-transform',
          checked ? 'translate-x-5' : 'translate-x-0.5',
        )}
      />
    </button>
  );
}


function ThresholdSlider({
  value,
  onChange,
}: {
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center gap-3 w-56">
      <input
        type="range"
        min={0.3}
        max={0.8}
        step={0.05}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="flex-1 accent-emerald-500"
      />
      <span className="text-sm tabular-nums font-medium w-12 text-right">
        {value.toFixed(2)}
      </span>
    </div>
  );
}


// ─── Profiles table ────────────────────────────────────────────────────


function ProfilesTable({
  profiles,
  pendingDelete,
  onEdit,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  profiles: FaceProfile[];
  pendingDelete: string | null;
  onEdit: (p: FaceProfile) => void;
  onRequestDelete: (id: string) => void;
  onCancelDelete: () => void;
  onConfirmDelete: (id: string) => void;
}) {
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase text-slate-500">
          <tr>
            <th className="py-2 pr-3">Nome</th>
            <th className="py-2 pr-3">Stato</th>
            <th className="py-2 pr-3 text-right">Descr.</th>
            <th className="py-2 pr-3 text-right">Match</th>
            <th className="py-2 pr-3 text-right">Soglia</th>
            <th className="py-2 pr-3">Ultimo</th>
            <th className="py-2 text-right">Azioni</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {profiles.map((p) => (
            <tr key={p.id}>
              <td className="py-2.5 pr-3">
                <div className="flex items-center gap-2">
                  <Initials name={p.displayName} />
                  <div>
                    <div className="font-medium">{p.displayName}</div>
                    {p.isChild && (
                      <Badge tone="accent" size="sm">
                        Bambino/a
                      </Badge>
                    )}
                  </div>
                </div>
              </td>
              <td className="py-2.5 pr-3">
                {p.active ? (
                  <Badge tone="ok" size="sm">
                    attivo
                  </Badge>
                ) : (
                  <Badge tone="neutral" size="sm">
                    disattivato
                  </Badge>
                )}
              </td>
              <td className="py-2.5 pr-3 text-right tabular-nums">{p.descriptorCount}</td>
              <td className="py-2.5 pr-3 text-right tabular-nums">{p.recognitionCount}</td>
              <td className="py-2.5 pr-3 text-right tabular-nums">
                {p.matchThreshold.toFixed(2)}
              </td>
              <td className="py-2.5 pr-3 text-slate-500">
                {fmtDate(p.lastRecognizedAt)}
              </td>
              <td className="py-2.5 text-right">
                <div className="inline-flex items-center gap-1">
                  <button
                    type="button"
                    aria-label="Modifica"
                    onClick={() => onEdit(p)}
                    className="px-2 py-1 rounded-md border border-slate-300 text-xs text-slate-700 hover:bg-slate-50"
                  >
                    Modifica
                  </button>
                  {pendingDelete === p.id ? (
                    <>
                      <button
                        type="button"
                        onClick={() => onConfirmDelete(p.id)}
                        className="px-2 py-1 rounded-md bg-rose-600 text-white text-xs font-medium hover:bg-rose-700"
                      >
                        Conferma
                      </button>
                      <button
                        type="button"
                        onClick={onCancelDelete}
                        className="px-2 py-1 rounded-md border border-slate-300 text-xs text-slate-600 hover:bg-slate-50"
                      >
                        Annulla
                      </button>
                    </>
                  ) : (
                    <IconButton
                      name="trash"
                      label="Elimina"
                      size="sm"
                      onClick={() => onRequestDelete(p.id)}
                    />

                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function Initials({ name }: { name: string }) {
  const initials = name
    .trim()
    .split(/\s+/)
    .map((s) => s[0]?.toUpperCase() ?? '')
    .slice(0, 2)
    .join('') || '?';
  return (
    <div className="h-9 w-9 rounded-full bg-emerald-100 text-emerald-800 flex items-center justify-center font-medium text-sm">
      {initials}
    </div>
  );
}


// ─── Edit modal ────────────────────────────────────────────────────────


function EditProfileModal({
  profile,
  onClose,
  onSaved,
}: {
  profile: FaceProfile;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [displayName, setDisplayName] = useState(profile.displayName);
  const [isChild, setIsChild] = useState(profile.isChild);
  const [threshold, setThreshold] = useState(profile.matchThreshold);
  const [active, setActive] = useState(profile.active);
  const [saving, setSaving] = useState(false);

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const patch: Parameters<typeof updateFaceProfile>[1] = {};
      const trimmed = displayName.trim();
      if (trimmed && trimmed !== profile.displayName) patch.display_name = trimmed;
      if (isChild !== profile.isChild) patch.is_child = isChild;
      if (threshold !== profile.matchThreshold) patch.match_threshold = threshold;
      if (active !== profile.active) patch.active = active;

      if (Object.keys(patch).length === 0) {
        onClose();
        return;
      }

      await updateFaceProfile(profile.id, patch);
      toast.push({ kind: 'ok', title: 'Profilo aggiornato' });
      onSaved();
    } catch (err) {
      toast.push({
        kind: 'alert',
        title: 'Aggiornamento fallito',
        body: err instanceof Error ? err.message : String(err),
      });
      setSaving(false);
    }
  }, [active, displayName, isChild, onClose, onSaved, profile, threshold, toast]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl max-w-md w-full p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold mb-4">Modifica profilo</h2>

        <label className="block mb-4">
          <span className="block text-sm font-medium mb-1">Nome</span>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            maxLength={80}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-200"
          />
        </label>

        <div className="space-y-3 mb-4">
          <label className="flex items-start gap-3 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={isChild}
              onChange={(e) => setIsChild(e.target.checked)}
              className="mt-1 w-4 h-4 accent-emerald-600"
            />
            <span>
              <span className="block font-medium text-sm">Bambino/a</span>
              <span className="block text-xs text-slate-500">
                Tolleranza match più ampia + voce morbida + dizionario semplice.
              </span>
            </span>
          </label>

          <label className="flex items-start gap-3 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={active}
              onChange={(e) => setActive(e.target.checked)}
              className="mt-1 w-4 h-4 accent-emerald-600"
            />
            <span>
              <span className="block font-medium text-sm">Profilo attivo</span>
              <span className="block text-xs text-slate-500">
                Disattivato = i descrittori restano nel DB ma CARA non li userà
                per il match. Reversibile.
              </span>
            </span>
          </label>
        </div>

        <div className="mb-6">
          <label className="block text-sm font-medium mb-1">
            Soglia di match: <span className="tabular-nums">{threshold.toFixed(2)}</span>
          </label>
          <input
            type="range"
            min={0.3}
            max={0.8}
            step={0.05}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-full accent-emerald-500"
          />
        </div>

        <div className="flex justify-end gap-2">
          <Button onClick={onClose} variant="ghost" disabled={saving}>
            Annulla
          </Button>
          <Button onClick={save} variant="primary" disabled={saving}>
            {saving ? 'Salvataggio…' : 'Salva'}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default AdminFacePage;
