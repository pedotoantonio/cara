/**
 * Step 1 — GDPR-compliant consent screen.
 *
 * The wizard cannot advance without an explicit, dated acceptance.
 * Backend records the acceptance under `face_profiles.consent_given_at`
 * + `face_profiles.consent_text_version` so we can prove later which
 * version of the notice was shown.
 */

import { useState } from 'react';

import { CONSENT_TEXT_VERSION } from './types';

interface Props {
  onAccept: () => void;
}

export function ConsentStep({ onAccept }: Props) {
  const [accepted, setAccepted] = useState(false);

  return (
    <div className="bg-white rounded-2xl shadow-sm border p-8">
      <h2 className="text-2xl font-semibold mb-2">Privacy e consenso</h2>
      <p className="text-sm text-slate-500 mb-6">
        Versione del testo: {CONSENT_TEXT_VERSION}
      </p>

      <div className="space-y-4 text-slate-700 leading-relaxed">
        <p>
          CARA può riconoscere chi è davanti alla camera del dispositivo per
          caricare automaticamente il profilo giusto (preferenze, voce,
          memoria, livello del linguaggio). Prima di registrarti leggi cosa
          succede ai tuoi dati.
        </p>

        <ul className="list-disc pl-6 space-y-2">
          <li>
            <strong>Nessuna foto del tuo volto lascia il browser.</strong>{' '}
            Il riconoscimento avviene interamente sul tuo dispositivo.
            Quello che salviamo è un vettore di 128 numeri — non è una
            foto e non è ricostruibile in una foto.
          </li>
          <li>
            Il vettore viene salvato sul server di casa, in chiaro ma
            protetto a livello di disco. Solo l’amministratore di CARA
            può vederlo.
          </li>
          <li>
            Puoi cancellare il tuo profilo in qualsiasi momento: ogni
            descrittore associato verrà eliminato.
          </li>
          <li>
            Il riconoscimento si disattiva da un interruttore in alto.
            CARA continua a funzionare normalmente senza.
          </li>
          <li>
            Niente cloud, niente Google, niente Amazon, niente Microsoft.
            Tutto rimane in casa.
          </li>
        </ul>
      </div>

      <label className="mt-8 flex items-start gap-3 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={accepted}
          onChange={(e) => setAccepted(e.target.checked)}
          className="mt-1 w-5 h-5 accent-emerald-600"
        />
        <span className="text-slate-800">
          Ho letto e accetto. Voglio registrare il mio volto su CARA.
        </span>
      </label>

      <div className="mt-8 flex justify-end">
        <button
          type="button"
          disabled={!accepted}
          onClick={onAccept}
          className={`px-6 py-2.5 rounded-lg font-medium transition-colors ${
            accepted
              ? 'bg-emerald-600 text-white hover:bg-emerald-700'
              : 'bg-slate-200 text-slate-400 cursor-not-allowed'
          }`}
        >
          Continua
        </button>
      </div>
    </div>
  );
}
