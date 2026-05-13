/**
 * Final step — review the 5 captures, gate on quality, save the profile.
 *
 * Gating rule: at least 4 of the 5 captures must clear the quality
 * threshold (0.8). If fewer pass we don't even let the user save —
 * recognition would be unreliable. Retry sends them back to the front
 * capture step with an empty capture list.
 */

import {
  MIN_PASSING_CAPTURES,
  QUALITY_THRESHOLD,
  type WizardCapture,
  type WizardDetails,
} from './types';


const ANGLE_LABEL: Record<WizardCapture['angle'], string> = {
  front: 'Frontale',
  left: 'Sinistra',
  right: 'Destra',
  smile: 'Sorriso',
  neutral: 'Neutro',
};


interface Props {
  details: WizardDetails;
  captures: WizardCapture[];
  saving: boolean;
  error: string | null;
  onSave: () => void;
  onRetry: () => void;
}

export function ReviewStep({
  details,
  captures,
  saving,
  error,
  onSave,
  onRetry,
}: Props) {
  const passing = captures.filter((c) => c.quality >= QUALITY_THRESHOLD);
  const passingCount = passing.length;
  const canSave = passingCount >= MIN_PASSING_CAPTURES;

  return (
    <div className="bg-white rounded-2xl shadow-sm border p-8">
      <h2 className="text-2xl font-semibold mb-2">Pronti per salvare</h2>
      <p className="text-sm text-slate-500 mb-6">
        Controlla la qualità delle acquisizioni e conferma.
      </p>

      <dl className="grid grid-cols-2 gap-y-2 gap-x-6 mb-6 text-sm">
        <dt className="text-slate-500">Nome</dt>
        <dd className="font-medium">{details.displayName}</dd>
        <dt className="text-slate-500">Bambino/a</dt>
        <dd className="font-medium">{details.isChild ? 'Sì' : 'No'}</dd>
        <dt className="text-slate-500">Acquisizioni</dt>
        <dd className="font-medium">
          {passingCount} su {captures.length} di qualità buona
          (≥ {QUALITY_THRESHOLD * 100}%)
        </dd>
      </dl>

      <ul className="border rounded-xl divide-y mb-6">
        {captures.map((c, i) => {
          const ok = c.quality >= QUALITY_THRESHOLD;
          return (
            <li
              key={`${c.angle}-${i}`}
              className="px-4 py-3 flex items-center justify-between"
            >
              <span className="font-medium">{ANGLE_LABEL[c.angle]}</span>
              <span
                className={`text-sm tabular-nums ${
                  ok ? 'text-emerald-700' : 'text-amber-700'
                }`}
              >
                {(c.quality * 100).toFixed(0)}% {ok ? '✓' : '⚠'}
              </span>
            </li>
          );
        })}
      </ul>

      {!canSave && (
        <div className="mb-4 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-amber-900 text-sm">
          Almeno {MIN_PASSING_CAPTURES} acquisizioni devono superare la
          soglia di qualità. Rifai le acquisizioni in un’area meglio
          illuminata.
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-lg bg-rose-50 border border-rose-200 px-4 py-3 text-rose-900 text-sm">
          Errore durante il salvataggio: {error}
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={onRetry}
          disabled={saving}
          className="px-4 py-2 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          Rifai le acquisizioni
        </button>
        <button
          type="button"
          onClick={onSave}
          disabled={!canSave || saving}
          className={`px-6 py-2.5 rounded-lg font-medium transition-colors ${
            canSave && !saving
              ? 'bg-emerald-600 text-white hover:bg-emerald-700'
              : 'bg-slate-200 text-slate-400 cursor-not-allowed'
          }`}
        >
          {saving ? 'Salvataggio…' : 'Salva profilo'}
        </button>
      </div>
    </div>
  );
}
