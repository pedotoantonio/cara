// /admin/devices — pair new surfaces + manage existing ones.
import { useEffect, useState } from 'react';

import {
  type Device,
  type SurfaceClass,
  deleteDevice,
  finalizePair,
  listDevices,
  patchDevice,
} from '../api/devices';

const SURFACES: { value: SurfaceClass; label: string; help: string }[] = [
  { value: 'mobile',  label: 'Mobile',  help: 'Telefono, tablet (uso famiglia)' },
  { value: 'desktop', label: 'Desktop', help: 'Browser su PC / laptop' },
  { value: 'wall',    label: 'Wall',    help: 'Touchscreen a parete (Pi 5 kiosk)' },
  { value: 'watch',   label: 'Watch',   help: 'Wearable / orologio (widget piccoli)' },
  { value: 'tv',      label: 'TV',      help: 'Schermo TV (visualizzazione lenta)' },
];

export function AdminDevicesPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [showPair, setShowPair] = useState(false);

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      setDevices(await listDevices());
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <main className="flex-1 overflow-y-auto bg-slate-900 text-slate-100">
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <header className="flex items-baseline justify-between">
          <div>
            <h1 className="text-xl font-medium">Dispositivi paired</h1>
            <p className="text-xs text-slate-500 mt-0.5">
              Wall, mobili, desktop e altri surface registrati per la famiglia.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setShowPair(true)}
              className="text-xs px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500"
            >
              + Aggiungi
            </button>
            <button
              type="button"
              onClick={refresh}
              className="text-xs text-emerald-300 hover:text-emerald-200 underline"
            >
              Aggiorna
            </button>
          </div>
        </header>

        {err && (
          <p className="text-xs text-rose-400 bg-rose-950/40 border border-rose-900 rounded-lg p-3">
            Errore: {err}
          </p>
        )}

        {loading ? (
          <p className="text-sm text-slate-500">Carico…</p>
        ) : devices.length === 0 ? (
          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-8 text-center">
            <p className="text-sm text-slate-400">
              Nessun dispositivo paired al momento.
            </p>
            <p className="text-xs text-slate-600 mt-2">
              Quando colleghi un Wall, un nuovo telefono o un PC, vai sul nuovo
              dispositivo, apri{' '}
              <code className="text-emerald-300">/pair</code> e inserisci qui il
              codice che vedi.
            </p>
          </div>
        ) : (
          <ul className="space-y-3">
            {devices.map((d) => (
              <DeviceCard
                key={d.id}
                device={d}
                onChanged={refresh}
                onError={(e) => setErr(e.message)}
              />
            ))}
          </ul>
        )}
      </div>

      {showPair && (
        <PairModal
          onClose={() => setShowPair(false)}
          onPaired={async () => {
            setShowPair(false);
            await refresh();
          }}
        />
      )}
    </main>
  );
}


function DeviceCard({
  device,
  onChanged,
  onError,
}: {
  device: Device;
  onChanged: () => void;
  onError: (e: Error) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(device.friendly_name);
  const [surface, setSurface] = useState<SurfaceClass>(device.surface_class);
  const [location, setLocation] = useState(device.location ?? '');
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await patchDevice(device.id, {
        friendly_name: name,
        surface_class: surface,
        location: location || null,
      });
      setEditing(false);
      onChanged();
    } catch (e) {
      onError(e as Error);
    } finally {
      setSaving(false);
    }
  }

  async function toggle() {
    try {
      await patchDevice(device.id, { enabled: !device.enabled });
      onChanged();
    } catch (e) {
      onError(e as Error);
    }
  }

  async function remove() {
    if (
      !window.confirm(
        `Cancellare ${device.friendly_name}? Il dispositivo non potrà più connettersi.`,
      )
    )
      return;
    try {
      await deleteDevice(device.id);
      onChanged();
    } catch (e) {
      onError(e as Error);
    }
  }

  const lastSeen = device.last_seen
    ? new Date(device.last_seen).toLocaleString('it-IT')
    : 'mai';

  return (
    <li className="rounded-2xl bg-slate-800/50 border border-slate-700 p-4 space-y-2">
      <div className="flex items-baseline justify-between">
        <div className="space-y-0.5">
          <h3 className="text-sm font-medium">
            {editing ? (
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={80}
                className="rounded-lg bg-slate-900 border border-slate-700 px-2 py-1 text-sm"
              />
            ) : (
              device.friendly_name
            )}
          </h3>
          <p className="text-xs text-slate-500">
            {editing ? (
              <select
                value={surface}
                onChange={(e) => setSurface(e.target.value as SurfaceClass)}
                className="rounded bg-slate-900 border border-slate-700 px-1 py-0.5 text-xs"
              >
                {SURFACES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            ) : (
              <>
                {SURFACES.find((s) => s.value === device.surface_class)?.label ??
                  device.surface_class}
                {device.location && ` · ${device.location}`}
              </>
            )}
          </p>
        </div>
        <span
          className={`text-[10px] px-2 py-0.5 rounded-full uppercase tracking-wide ${
            device.enabled && device.status === 'online'
              ? 'bg-emerald-900/40 text-emerald-300 border border-emerald-800'
              : device.enabled
                ? 'bg-amber-900/40 text-amber-300 border border-amber-800'
                : 'bg-slate-700 text-slate-400 border border-slate-600'
          }`}
        >
          {device.status}
        </span>
      </div>

      {editing && (
        <input
          type="text"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          maxLength={80}
          placeholder="Stanza (es. soggiorno)"
          className="w-full rounded-lg bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
        />
      )}

      <div className="text-[11px] text-slate-500 flex flex-wrap gap-x-3">
        <span>Visto: {lastSeen}</span>
      </div>

      <div className="flex gap-2 pt-1 text-xs">
        {!editing ? (
          <>
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="px-3 py-1 rounded-lg bg-slate-700 hover:bg-slate-600"
            >
              Modifica
            </button>
            <button
              type="button"
              onClick={toggle}
              className={`px-3 py-1 rounded-lg ${
                device.enabled
                  ? 'bg-amber-700 hover:bg-amber-600'
                  : 'bg-emerald-600 hover:bg-emerald-500'
              }`}
            >
              {device.enabled ? 'Disabilita' : 'Abilita'}
            </button>
            <button
              type="button"
              onClick={remove}
              className="ml-auto px-3 py-1 rounded-lg bg-rose-900/60 hover:bg-rose-800"
            >
              Cancella
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="px-3 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40"
            >
              {saving ? 'Salvo…' : 'Salva'}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setName(device.friendly_name);
                setSurface(device.surface_class);
                setLocation(device.location ?? '');
              }}
              className="px-3 py-1 rounded-lg bg-slate-700 hover:bg-slate-600"
            >
              Annulla
            </button>
          </>
        )}
      </div>
    </li>
  );
}


function PairModal({
  onClose,
  onPaired,
}: {
  onClose: () => void;
  onPaired: () => void;
}) {
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [surface, setSurface] = useState<SurfaceClass>('mobile');
  const [location, setLocation] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function go() {
    setErr(null);
    setSaving(true);
    try {
      await finalizePair({
        code: code.trim(),
        friendly_name: name.trim(),
        surface_class: surface,
        location: location.trim() || null,
      });
      onPaired();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-label="Aggiungi dispositivo"
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-3"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <h2 className="text-base font-medium">Aggiungi un dispositivo</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Sul dispositivo nuovo, apri{' '}
            <code className="text-emerald-300">https://192.168.1.23:8455/pair</code>{' '}
            per ottenere il codice di 6 cifre.
          </p>
        </header>

        <label className="block space-y-1 text-xs">
          <span className="text-slate-400">Codice (6 cifre)</span>
          <input
            type="text"
            inputMode="numeric"
            pattern="\d*"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
            placeholder="123456"
            className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-base font-mono tracking-widest text-center"
          />
        </label>

        <label className="block space-y-1 text-xs">
          <span className="text-slate-400">Nome (es. "Wall soggiorno")</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={80}
            className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm"
          />
        </label>

        <label className="block space-y-1 text-xs">
          <span className="text-slate-400">Tipo</span>
          <select
            value={surface}
            onChange={(e) => setSurface(e.target.value as SurfaceClass)}
            className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm"
          >
            {SURFACES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label} — {s.help}
              </option>
            ))}
          </select>
        </label>

        <label className="block space-y-1 text-xs">
          <span className="text-slate-400">Stanza (opzionale)</span>
          <input
            type="text"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            maxLength={80}
            placeholder="soggiorno"
            className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm"
          />
        </label>

        {err && (
          <p className="text-xs text-rose-400 bg-rose-950/40 border border-rose-900 rounded-lg p-2">
            {err}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs rounded-lg bg-slate-700 hover:bg-slate-600"
          >
            Annulla
          </button>
          <button
            type="button"
            onClick={go}
            disabled={saving || code.length !== 6 || !name.trim()}
            className="px-3 py-1.5 text-xs rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40"
          >
            {saving ? 'Aggiungo…' : 'Conferma'}
          </button>
        </div>
      </div>
    </div>
  );
}
