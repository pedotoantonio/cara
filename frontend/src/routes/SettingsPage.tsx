import { useEffect, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';

import { changePassword, updateMe, type User } from '../api/auth';
import { loadPrefs, savePrefs } from '../lib/userPrefs';
import { playSound, setSoundsEnabled, setVolume } from '../lib/sounds';

interface OutletCtx {
  user: User;
  refreshMe: () => void;
}

export function SettingsPage() {
  const { user, refreshMe } = useOutletContext<OutletCtx>();

  const [fullName, setFullName] = useState(user.full_name ?? '');
  const [birthDate, setBirthDate] = useState(user.birth_date ?? '');
  const [profileMsg, setProfileMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);

  const [curPwd, setCurPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [confirmPwd, setConfirmPwd] = useState('');
  const [pwdMsg, setPwdMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [savingPwd, setSavingPwd] = useState(false);

  // Sound prefs (per-device, in localStorage)
  const initial = loadPrefs();
  const [soundsOn, setSoundsOn] = useState(initial.soundsEnabled);
  const [vol, setVol] = useState(initial.soundsVolume);
  const [wakeWordOn, setWakeWordOn] = useState(initial.wakeWordEnabled);

  useEffect(() => {
    setSoundsEnabled(soundsOn);
    setVolume(vol);
    savePrefs({ ...loadPrefs(), soundsEnabled: soundsOn, soundsVolume: vol, wakeWordEnabled: wakeWordOn });
  }, [soundsOn, vol, wakeWordOn]);

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    setProfileMsg(null);
    setSavingProfile(true);
    try {
      await updateMe({
        full_name: fullName.trim() || null,
        birth_date: birthDate || null,
      });
      setProfileMsg({ ok: true, text: 'Profilo aggiornato' });
      refreshMe();
    } catch (err) {
      setProfileMsg({ ok: false, text: (err as Error).message });
    } finally {
      setSavingProfile(false);
    }
  }

  async function savePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwdMsg(null);
    if (newPwd !== confirmPwd) {
      setPwdMsg({ ok: false, text: 'Le password nuove non coincidono' });
      return;
    }
    if (newPwd.length < 8) {
      setPwdMsg({ ok: false, text: 'La nuova password deve avere almeno 8 caratteri' });
      return;
    }
    setSavingPwd(true);
    try {
      await changePassword(curPwd, newPwd);
      setPwdMsg({ ok: true, text: 'Password aggiornata' });
      setCurPwd('');
      setNewPwd('');
      setConfirmPwd('');
    } catch (err) {
      setPwdMsg({ ok: false, text: (err as Error).message });
    } finally {
      setSavingPwd(false);
    }
  }

  return (
    <main className="flex-1 overflow-y-auto bg-slate-900 text-slate-100">
      <div className="max-w-xl mx-auto p-6 space-y-8">
        <header>
          <h1 className="text-xl font-medium">Impostazioni</h1>
          <p className="text-xs text-slate-500 mt-0.5">{user.email}</p>
        </header>

        <section className="space-y-3 rounded-2xl bg-slate-800/60 border border-slate-700 p-5">
          <h2 className="text-sm font-medium">Profilo</h2>
          <form onSubmit={saveProfile} className="space-y-3">
            <div>
              <label className="block text-xs text-slate-400 mb-1">Nome completo</label>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                maxLength={120}
                placeholder="Antonio Pedoto"
                className="w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">
                Data di nascita (per il compleanno)
              </label>
              <input
                type="date"
                value={birthDate}
                onChange={(e) => setBirthDate(e.target.value)}
                className="w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Email (non modificabile)</label>
              <input
                type="email"
                value={user.email}
                disabled
                className="w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-500"
              />
            </div>
            {profileMsg && (
              <p className={`text-xs ${profileMsg.ok ? 'text-emerald-400' : 'text-rose-400'}`}>
                {profileMsg.text}
              </p>
            )}
            <button
              type="submit"
              disabled={savingProfile}
              className="rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-4 py-2 text-sm font-medium"
            >
              {savingProfile ? 'Salvo…' : 'Salva profilo'}
            </button>
          </form>
        </section>

        <section className="space-y-3 rounded-2xl bg-slate-800/60 border border-slate-700 p-5">
          <h2 className="text-sm font-medium">Cambia password</h2>
          <form onSubmit={savePassword} className="space-y-3">
            <div>
              <label className="block text-xs text-slate-400 mb-1">Password attuale</label>
              <input
                type="password"
                required
                value={curPwd}
                onChange={(e) => setCurPwd(e.target.value)}
                autoComplete="current-password"
                className="w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Nuova password (almeno 8 caratteri)</label>
              <input
                type="password"
                required
                minLength={8}
                value={newPwd}
                onChange={(e) => setNewPwd(e.target.value)}
                autoComplete="new-password"
                className="w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Ripeti nuova password</label>
              <input
                type="password"
                required
                value={confirmPwd}
                onChange={(e) => setConfirmPwd(e.target.value)}
                autoComplete="new-password"
                className="w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
              />
            </div>
            {pwdMsg && (
              <p className={`text-xs ${pwdMsg.ok ? 'text-emerald-400' : 'text-rose-400'}`}>
                {pwdMsg.text}
              </p>
            )}
            <button
              type="submit"
              disabled={savingPwd || !curPwd || !newPwd || !confirmPwd}
              className="rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-4 py-2 text-sm font-medium"
            >
              {savingPwd ? 'Aggiorno…' : 'Aggiorna password'}
            </button>
          </form>
        </section>

        <section className="space-y-3 rounded-2xl bg-slate-800/60 border border-slate-700 p-5">
          <h2 className="text-sm font-medium">Voce</h2>
          <label className="flex items-start gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={wakeWordOn}
              onChange={(e) => setWakeWordOn(e.target.checked)}
              className="accent-emerald-500 mt-1"
            />
            <span>
              Ascolto continuo della parola <span className="text-emerald-300">"CARA"</span>
              <span className="block text-xs text-slate-500 mt-0.5">
                Quando attivo, basta dire "CARA, …" per iniziare a parlare senza toccare il microfono.
                Funziona solo in primo piano nella scheda del browser; in background il microfono viene
                rilasciato dal sistema. Riavvia la home dopo aver cambiato questa impostazione.
              </span>
            </span>
          </label>
        </section>

        <section className="space-y-3 rounded-2xl bg-slate-800/60 border border-slate-700 p-5">
          <h2 className="text-sm font-medium">Suoni dell'interfaccia</h2>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={soundsOn}
              onChange={(e) => setSoundsOn(e.target.checked)}
              className="accent-emerald-500"
            />
            Suoni attivi (notifiche, conferme, errori)
          </label>
          <div>
            <label className="block text-xs text-slate-400 mb-1">
              Volume: {Math.round(vol * 100)}%
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={vol}
              onChange={(e) => setVol(Number(e.target.value))}
              disabled={!soundsOn}
              className="w-full accent-emerald-500"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            {(['notify', 'confirm', 'celebrate', 'error', 'wake'] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => playSound(s)}
                disabled={!soundsOn}
                className="rounded-lg bg-slate-900 hover:bg-slate-700 disabled:opacity-40 border border-slate-700 px-3 py-1 text-xs"
              >
                ▶ {s}
              </button>
            ))}
          </div>
        </section>

        {user.is_admin && (
          <section className="space-y-2 rounded-2xl bg-slate-800/40 border border-slate-700/60 p-5 text-xs text-slate-400">
            <h2 className="text-sm font-medium text-slate-200">Strumenti admin</h2>
            <p>
              <Link to="/admin" className="text-emerald-300 hover:text-emerald-200">
                Pannello admin →
              </Link>{' '}
              Funzionalità on/off, prompt CARA, validazione, parametri risposta, audit log.
            </p>
            <p>
              <Link to="/face-lab" className="text-emerald-300 hover:text-emerald-200">
                Face Lab →
              </Link>{' '}
              Sandbox per esaminare ogni combinazione di stato × emozione del volto di CARA.
            </p>
          </section>
        )}

        <section className="space-y-2 rounded-2xl bg-slate-800/40 border border-slate-700/60 p-5 text-xs text-slate-400">
          <h2 className="text-sm font-medium text-slate-200">Informazioni</h2>
          <p>CARA — Casa AI for Routines &amp; Activities</p>
          <p>Versione 0.1 · build privato</p>
          <p>
            Costruita con software open source. Vedi i file{' '}
            <code className="text-emerald-300">/opt/cara/LICENSE</code> e{' '}
            <code className="text-emerald-300">/opt/cara/NOTICE</code> sul server per la lista completa
            delle licenze e attribuzioni dei componenti utilizzati.
          </p>
          <p>
            AI in locale: Qwen2.5-1.5B su NPU RK3588 via RKLLM runtime; nessun dato lascia il dispositivo
            di casa.
          </p>
        </section>
      </div>
    </main>
  );
}
