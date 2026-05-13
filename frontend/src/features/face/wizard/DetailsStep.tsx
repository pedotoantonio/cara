/**
 * Step 2 — display name + child flag.
 *
 * The child flag is consumed by CARA Core to (a) load the simplified
 * dictionary, (b) soften the TTS voice, (c) gate dangerous smart-home
 * actions. It also widens the match tolerance because children's faces
 * change visibly over months and the descriptors drift faster.
 */

import { useState } from 'react';

import type { WizardDetails } from './types';

interface Props {
  initial: WizardDetails;
  onSubmit: (details: WizardDetails) => void;
}

export function DetailsStep({ initial, onSubmit }: Props) {
  const [displayName, setDisplayName] = useState(initial.displayName);
  const [isChild, setIsChild] = useState(initial.isChild);

  const trimmed = displayName.trim();
  const valid = trimmed.length >= 1 && trimmed.length <= 80;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid) return;
        onSubmit({ displayName: trimmed, isChild });
      }}
      className="bg-white rounded-2xl shadow-sm border p-8"
    >
      <h2 className="text-2xl font-semibold mb-2">Chi sei?</h2>
      <p className="text-sm text-slate-500 mb-6">
        Questi dati restano in casa. Il nome è quello che CARA userà
        per salutarti.
      </p>

      <label className="block">
        <span className="block text-sm font-medium text-slate-700 mb-1">
          Nome visualizzato
        </span>
        <input
          type="text"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          maxLength={80}
          autoFocus
          className="w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-200"
          placeholder="Es. Antonio, Sara, Matteo…"
        />
      </label>

      <label className="mt-6 flex items-start gap-3 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={isChild}
          onChange={(e) => setIsChild(e.target.checked)}
          className="mt-1 w-5 h-5 accent-emerald-600"
        />
        <span>
          <span className="block font-medium">È un bambino o una bambina</span>
          <span className="block text-sm text-slate-500">
            CARA userà il dizionario semplificato e una voce più morbida.
            La soglia di riconoscimento sarà più tollerante perché i volti
            dei bambini cambiano spesso.
          </span>
        </span>
      </label>

      <div className="mt-8 flex justify-end">
        <button
          type="submit"
          disabled={!valid}
          className={`px-6 py-2.5 rounded-lg font-medium transition-colors ${
            valid
              ? 'bg-emerald-600 text-white hover:bg-emerald-700'
              : 'bg-slate-200 text-slate-400 cursor-not-allowed'
          }`}
        >
          Inizia la registrazione
        </button>
      </div>
    </form>
  );
}
