/**
 * Post-enrollment confirmation page. Reachable via `navigate('/face/enroll/done',
 * { state: { displayName } })` from the wizard's save handler.
 *
 * Kept separate from the wizard so a refresh on this URL doesn't
 * trigger a redo of the consent + capture flow.
 */

import { Link, useLocation, useNavigate } from 'react-router-dom';


interface DoneState {
  displayName?: string;
  captureCount?: number;
}


export default function FaceEnrollDonePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const state = (location.state ?? null) as DoneState | null;

  const displayName = state?.displayName ?? 'profilo';
  const captureCount = state?.captureCount ?? 0;

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
      <div className="max-w-md w-full bg-white rounded-2xl shadow-sm border p-8 text-center">
        <div className="text-5xl mb-4" aria-hidden>
          ✓
        </div>
        <h1 className="text-2xl font-semibold mb-2">Registrazione completata</h1>
        <p className="text-slate-600 mb-6">
          CARA ora riconosce <strong>{displayName}</strong>. Abbiamo
          salvato {captureCount} acquisizioni del volto. Quando ti
          avvicinerai a una camera, ti saluterò per nome.
        </p>
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={() => navigate('/face/enroll', { replace: true })}
            className="w-full px-4 py-2.5 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-50"
          >
            Registra un altro volto
          </button>
          <Link
            to="/"
            className="w-full px-4 py-2.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 font-medium"
          >
            Torna alla home
          </Link>
        </div>
      </div>
    </div>
  );
}
