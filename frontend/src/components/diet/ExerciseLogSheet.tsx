// ExerciseLogSheet — registra un allenamento. Scegli l'attività dal
// catalogo MET, indica i minuti → il backend calcola le kcal bruciate
// (MET × peso × ore).

import { useEffect, useState } from 'react';

import { addExercise, getExerciseCatalog, type MetActivity } from '../../api/diet';
import { BottomSheet, Button } from '../../design';

interface Props {
  open: boolean;
  onClose: () => void;
  onLogged?: () => void;
}

export function ExerciseLogSheet({ open, onClose, onLogged }: Props) {
  const [catalog, setCatalog] = useState<MetActivity[]>([]);
  const [slug, setSlug] = useState('');
  const [minutes, setMinutes] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && catalog.length === 0) {
      getExerciseCatalog().then(setCatalog).catch(() => undefined);
    }
  }, [open, catalog.length]);

  async function submit() {
    const act = catalog.find((a) => a.slug === slug);
    if (!act) {
      setError('Scegli un’attività');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await addExercise({ activity: act.label, slug: act.slug, duration_min: minutes });
      onLogged?.();
      onClose();
      setSlug('');
      setMinutes(30);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Errore');
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet open={open} onClose={onClose} title="Registra allenamento" subtitle="Calorie bruciate dal MET">
      <div className="space-y-4">
        <div>
          <label className="text-sm text-fg-muted">Attività</label>
          <select
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            className="w-full mt-1 rounded-2xl bg-surface1 ring-1 ring-fg/10 px-4 h-12 focus:outline-none focus:ring-accent/40"
          >
            <option value="">— scegli —</option>
            {catalog.map((a) => (
              <option key={a.slug} value={a.slug}>
                {a.label} · {a.met} MET
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-sm text-fg-muted">Durata: {minutes} min</label>
          <input
            type="range"
            min={5}
            max={180}
            step={5}
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
            className="w-full mt-2 accent-accent"
          />
        </div>

        {error && <p className="text-sm text-alert">{error}</p>}

        <Button variant="primary" size="lg" fullWidth loading={busy} disabled={!slug || busy} onClick={submit}>
          Registra
        </Button>
      </div>
    </BottomSheet>
  );
}
