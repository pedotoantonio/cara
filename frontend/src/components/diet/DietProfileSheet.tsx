// DietProfileSheet — dati per il fabbisogno calorico (Mifflin-St Jeor):
// sesso, data di nascita, altezza, peso, livello di attività, obiettivo.

import { useEffect, useState } from 'react';

import {
  ACTIVITY_LABEL,
  GOAL_LABEL,
  getProfile,
  putProfile,
  type ActivityLevel,
  type DietProfile,
  type Goal,
} from '../../api/diet';
import { BottomSheet, Button } from '../../design';

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved?: (p: DietProfile) => void;
}

const ACTIVITIES: ActivityLevel[] = ['sedentary', 'light', 'moderate', 'very', 'extra'];
const GOALS: Goal[] = ['maintain', 'lose', 'gain'];

export function DietProfileSheet({ open, onClose, onSaved }: Props) {
  const [p, setP] = useState<Partial<DietProfile>>({ activity_level: 'moderate', goal: 'maintain' });
  const [preview, setPreview] = useState<DietProfile | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) getProfile().then((x) => { setP(x); setPreview(x); }).catch(() => undefined);
  }, [open]);

  function set<K extends keyof DietProfile>(k: K, v: DietProfile[K]) {
    setP((prev) => ({ ...prev, [k]: v }));
  }

  async function save() {
    setBusy(true);
    try {
      const saved = await putProfile({
        sex: p.sex ?? null,
        birth_date: p.birth_date ?? null,
        height_cm: p.height_cm ?? null,
        weight_kg: p.weight_kg ?? null,
        activity_level: p.activity_level,
        goal: p.goal,
      });
      onSaved?.(saved);
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet open={open} onClose={onClose} title="Il tuo profilo" subtitle="Per calcolare il fabbisogno calorico">
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Labeled label="Sesso">
            <select
              value={p.sex ?? ''}
              onChange={(e) => set('sex', (e.target.value || null) as 'M' | 'F' | null)}
              className="w-full rounded-xl bg-surface1 ring-1 ring-fg/10 px-3 h-11"
            >
              <option value="">—</option>
              <option value="M">Uomo</option>
              <option value="F">Donna</option>
            </select>
          </Labeled>
          <Labeled label="Data di nascita">
            <input
              type="date"
              value={p.birth_date ?? ''}
              onChange={(e) => set('birth_date', e.target.value || null)}
              className="w-full rounded-xl bg-surface1 ring-1 ring-fg/10 px-3 h-11"
            />
          </Labeled>
          <Labeled label="Altezza (cm)">
            <input
              type="number"
              value={p.height_cm ?? ''}
              onChange={(e) => set('height_cm', e.target.value ? Number(e.target.value) : null)}
              className="w-full rounded-xl bg-surface1 ring-1 ring-fg/10 px-3 h-11"
            />
          </Labeled>
          <Labeled label="Peso (kg)">
            <input
              type="number"
              step="0.1"
              value={p.weight_kg ?? ''}
              onChange={(e) => set('weight_kg', e.target.value ? Number(e.target.value) : null)}
              className="w-full rounded-xl bg-surface1 ring-1 ring-fg/10 px-3 h-11"
            />
          </Labeled>
        </div>

        <Labeled label="Livello di attività">
          <select
            value={p.activity_level}
            onChange={(e) => set('activity_level', e.target.value as ActivityLevel)}
            className="w-full rounded-xl bg-surface1 ring-1 ring-fg/10 px-3 h-11"
          >
            {ACTIVITIES.map((a) => (
              <option key={a} value={a}>{ACTIVITY_LABEL[a]}</option>
            ))}
          </select>
        </Labeled>

        <Labeled label="Obiettivo">
          <select
            value={p.goal}
            onChange={(e) => set('goal', e.target.value as Goal)}
            className="w-full rounded-xl bg-surface1 ring-1 ring-fg/10 px-3 h-11"
          >
            {GOALS.map((g) => (
              <option key={g} value={g}>{GOAL_LABEL[g]}</option>
            ))}
          </select>
        </Labeled>

        {preview?.complete && (
          <div className="rounded-xl bg-surface2 px-4 py-3 text-sm">
            <div className="flex justify-between"><span className="text-fg-muted">BMR</span><b>{preview.bmr} kcal</b></div>
            <div className="flex justify-between"><span className="text-fg-muted">TDEE</span><b>{preview.tdee} kcal</b></div>
            <div className="flex justify-between"><span className="text-fg-muted">Obiettivo giornaliero</span><b>{preview.daily_target} kcal</b></div>
          </div>
        )}

        <Button variant="primary" size="lg" fullWidth loading={busy} onClick={save}>
          Salva profilo
        </Button>
        <p className="text-2xs text-fg-muted text-center">
          Calcolo Mifflin-St Jeor. Dati sul tuo dispositivo/server, mai nel cloud.
        </p>
      </div>
    </BottomSheet>
  );
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm text-fg-muted">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
