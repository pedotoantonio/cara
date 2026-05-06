// /setup — first-run wizard. 8 steps, italian UI, idempotent, resumable.
//
// Mounts at /setup. The App router decides whether to redirect here
// based on /setup/status. Inside, each step is a small self-contained
// component. The shell handles step navigation + draft persistence.
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { setTokens } from '../api/auth';
import {
  SETUP_STEPS,
  type SetupStatus,
  type SetupStep,
  completeIntegrations,
  completeSetup,
  createAdmin,
  generateVapid,
  getSetupStatus,
  regenerateCert,
  resetSetup,
  saveCloud,
  saveFamily,
  saveFeatureFlags,
  saveGoogle,
  saveHomeAssistant,
  saveLLM,
  saveTelegram,
  saveVoice,
  skipCert,
  testCloud,
  testHomeAssistant,
} from '../api/setup';

const STEP_LABELS: Record<SetupStep, string> = {
  admin: 'Amministratore',
  tls: 'Sicurezza',
  family: 'Famiglia',
  voice: 'Voce',
  llm: 'Intelligenza',
  integrations: 'Integrazioni',
  google_cloud: 'Google e Cloud',
  feature_flags: 'Privacy',
};


export function SetupPage() {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [stepIdx, setStepIdx] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    (async () => {
      try {
        const s = await getSetupStatus();
        setStatus(s);
        if (s.completed) {
          setDone(true);
          return;
        }
        const idx = SETUP_STEPS.indexOf(s.current_step as SetupStep);
        if (idx >= 0) setStepIdx(idx);
      } catch (e) {
        setErr((e as Error).message);
      }
    })();
  }, []);

  if (done) {
    return <CompleteScreen onContinue={() => navigate('/', { replace: true })} />;
  }

  if (!status) {
    return (
      <main className="min-h-dvh flex items-center justify-center bg-slate-900 text-slate-100">
        <p className="text-sm text-slate-400 animate-pulse">Carico configurazione…</p>
      </main>
    );
  }

  const currentStep = SETUP_STEPS[stepIdx];
  const isCompleted = (s: SetupStep) => status.completed_steps.includes(s);

  function next() {
    if (stepIdx + 1 < SETUP_STEPS.length) {
      setStepIdx(stepIdx + 1);
      setErr(null);
    }
  }

  function back() {
    if (stepIdx > 0) {
      setStepIdx(stepIdx - 1);
      setErr(null);
    }
  }

  async function finish() {
    try {
      const r = await completeSetup({});
      setDone(true);
      if (r.needs_restart) {
        // Keep the user informed.
        window.alert(
          'Configurazione completata. Il backend deve essere riavviato per ' +
            'applicare alcune modifiche (verrà fatto adesso). Attendi qualche secondo.',
        );
      }
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <main className="min-h-dvh bg-slate-900 text-slate-100 flex flex-col">
      <header className="border-b border-slate-800 px-6 py-4">
        <div className="max-w-3xl mx-auto flex items-baseline justify-between gap-4">
          <div>
            <h1 className="text-2xl font-light tracking-tight">cara · setup</h1>
            <p className="text-xs text-slate-500">
              Configurazione iniziale — 8 passi guidati
            </p>
          </div>
          <span className="text-xs text-slate-500">
            Passo {stepIdx + 1} di {SETUP_STEPS.length}
          </span>
        </div>

        {/* Stepper */}
        <ol className="max-w-3xl mx-auto mt-4 flex gap-1.5">
          {SETUP_STEPS.map((s, i) => (
            <li
              key={s}
              className={`flex-1 h-1.5 rounded-full transition-colors ${
                i === stepIdx
                  ? 'bg-emerald-500'
                  : isCompleted(s) || i < stepIdx
                    ? 'bg-emerald-700'
                    : 'bg-slate-700'
              }`}
              aria-label={STEP_LABELS[s]}
            />
          ))}
        </ol>
      </header>

      <section className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-2xl mx-auto space-y-4">
          <h2 className="text-lg font-medium">{STEP_LABELS[currentStep]}</h2>

          {err && (
            <p className="rounded-xl bg-rose-950/40 border border-rose-900 text-rose-300 text-sm p-3">
              {err}
            </p>
          )}

          {currentStep === 'admin' && (
            <Step1Admin
              hasAdmin={status.has_admin}
              onError={setErr}
              onSaved={(tokens) => {
                setTokens(tokens.access_token, tokens.refresh_token);
                next();
              }}
            />
          )}
          {currentStep === 'tls' && <Step2TLS onError={setErr} onDone={next} />}
          {currentStep === 'family' && <Step3Family onError={setErr} onDone={next} />}
          {currentStep === 'voice' && <Step4Voice onError={setErr} onDone={next} />}
          {currentStep === 'llm' && <Step5LLM onError={setErr} onDone={next} />}
          {currentStep === 'integrations' && (
            <Step6Integrations onError={setErr} onDone={next} />
          )}
          {currentStep === 'google_cloud' && (
            <Step7GoogleCloud onError={setErr} onDone={next} />
          )}
          {currentStep === 'feature_flags' && (
            <Step8FeatureFlags
              onError={setErr}
              onDone={() => {
                finish();
              }}
            />
          )}
        </div>
      </section>

      <footer className="border-t border-slate-800 px-6 py-3">
        <div className="max-w-3xl mx-auto flex justify-between items-center gap-2">
          <button
            type="button"
            onClick={back}
            disabled={stepIdx === 0}
            className="text-xs px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-30"
          >
            ← Indietro
          </button>
          <p className="text-[11px] text-slate-600">
            I dati sono salvati ad ogni passo — puoi chiudere e riprendere dopo.
          </p>
        </div>
      </footer>
    </main>
  );
}


// ---------------------------------------------------------------------------
// Step 1 — Admin
// ---------------------------------------------------------------------------


function Step1Admin({
  hasAdmin,
  onError,
  onSaved,
}: {
  hasAdmin: boolean;
  onError: (e: string | null) => void;
  onSaved: (tokens: { access_token: string; refresh_token: string }) => void;
}) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [fullName, setFullName] = useState('');
  const [birthDate, setBirthDate] = useState('');
  const [timezone, setTimezone] = useState('Europe/Rome');
  const [saving, setSaving] = useState(false);

  if (hasAdmin) {
    return (
      <div className="rounded-xl bg-amber-950/30 border border-amber-900 text-amber-200 text-sm p-4 space-y-2">
        <p>Esiste già un amministratore in questo sistema.</p>
        <p className="text-xs text-amber-300/80">
          Accedi con il tuo account già esistente per riconfigurare i passaggi
          successivi. Se non ricordi le credenziali, dal terminale del server:{' '}
          <code>docker exec cara-backend python -m cara.bootstrap reset-admin</code>.
        </p>
      </div>
    );
  }

  async function go() {
    onError(null);
    if (password !== confirm) {
      onError('Le password non coincidono');
      return;
    }
    if (password.length < 12) {
      onError('La password deve avere almeno 12 caratteri');
      return;
    }
    setSaving(true);
    try {
      const r = await createAdmin({
        email,
        password,
        full_name: fullName,
        birth_date: birthDate || undefined,
        timezone,
      });
      onSaved({ access_token: r.access_token, refresh_token: r.refresh_token });
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        Crea l'account amministratore: chi può configurare CARA, aggiungere
        utenti famiglia, abilitare integrazioni.
      </p>
      <Field label="Email" type="email" value={email} onChange={setEmail} required />
      <Field label="Nome completo" value={fullName} onChange={setFullName} required />
      <Field label="Data di nascita" type="date" value={birthDate} onChange={setBirthDate} />
      <Field
        label="Password (almeno 12 caratteri)"
        type="password" value={password} onChange={setPassword} required
      />
      <Field
        label="Ripeti password"
        type="password" value={confirm} onChange={setConfirm} required
      />
      <Field label="Fuso orario" value={timezone} onChange={setTimezone} />
      <PrimaryButton onClick={go} disabled={saving} label={saving ? 'Salvo…' : 'Crea amministratore'} />
    </div>
  );
}


// ---------------------------------------------------------------------------
// Step 2 — TLS
// ---------------------------------------------------------------------------


function Step2TLS({
  onError,
  onDone,
}: {
  onError: (e: string | null) => void;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [fingerprint, setFingerprint] = useState<string | null>(null);
  const [skipped, setSkipped] = useState(false);

  async function regen() {
    onError(null);
    setBusy(true);
    try {
      const r = await regenerateCert({});
      setFingerprint(r.fingerprint_sha256);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function skip() {
    onError(null);
    setBusy(true);
    try {
      await skipCert({});
      setSkipped(true);
      onDone();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        Il certificato HTTPS protegge la connessione tra browser e CARA.
        Genera una CA locale per evitare i warning sui dispositivi famiglia.
      </p>
      {fingerprint && (
        <div className="rounded-xl bg-emerald-950/30 border border-emerald-900 text-emerald-200 text-sm p-4 space-y-2">
          <p>✓ Certificato rigenerato.</p>
          <p className="text-xs">Fingerprint SHA-256:</p>
          <code className="text-[10px] block break-all text-emerald-300">
            {fingerprint}
          </code>
          <p className="text-xs">
            Scarica la CA su ogni dispositivo famiglia da:{' '}
            <a
              href="http://192.168.1.23/cara-ca.crt"
              className="underline text-emerald-300"
              target="_blank" rel="noreferrer"
            >
              http://192.168.1.23/cara-ca.crt
            </a>
          </p>
          <button
            type="button" onClick={onDone}
            className="mt-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-xs"
          >
            Ho scaricato la CA, prosegui →
          </button>
        </div>
      )}
      {!fingerprint && !skipped && (
        <div className="flex gap-2">
          <PrimaryButton onClick={regen} disabled={busy} label={busy ? 'Rigenero…' : 'Rigenera CA + cert'} />
          <button
            type="button" onClick={skip} disabled={busy}
            className="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-xs"
          >
            Salta (lascia self-signed)
          </button>
        </div>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Step 3 — Family
// ---------------------------------------------------------------------------


function Step3Family({
  onError,
  onDone,
}: {
  onError: (e: string | null) => void;
  onDone: () => void;
}) {
  const [name, setName] = useState('');
  const [glossary, setGlossary] = useState('');
  const [size, setSize] = useState(4);
  const [language, setLanguage] = useState('it');
  const [busy, setBusy] = useState(false);

  async function go() {
    onError(null);
    setBusy(true);
    try {
      await saveFamily({
        family_name: name.trim(),
        glossary: glossary
          .split(/[,;\n]/)
          .map((s) => s.trim())
          .filter(Boolean),
        family_size: size,
        language,
      });
      onDone();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        Identità famiglia. La lista nomi/cognomi alimenta il riconoscimento
        dei membri quando CARA legge messaggi/note.
      </p>
      <Field label="Nome famiglia (es. 'Famiglia Pedoto')" value={name} onChange={setName} />
      <Field
        label="Nomi e cognomi (separati da virgola o riga)"
        value={glossary} onChange={setGlossary}
        textarea
      />
      <Field
        label={`Quanti siete? ${size}`}
        type="range" min={1} max={12} value={size}
        onChange={(v) => setSize(Number(v))}
      />
      <label className="block space-y-1 text-xs">
        <span className="text-slate-400">Lingua principale</span>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm"
        >
          <option value="it">Italiano</option>
          <option value="en">English</option>
        </select>
      </label>
      <PrimaryButton onClick={go} disabled={busy} label={busy ? 'Salvo…' : 'Avanti →'} />
    </div>
  );
}


// ---------------------------------------------------------------------------
// Step 4 — Voice
// ---------------------------------------------------------------------------


function Step4Voice({
  onError,
  onDone,
}: {
  onError: (e: string | null) => void;
  onDone: () => void;
}) {
  const [voiceName, setVoiceName] = useState('it_IT-paola-medium');
  const [rate, setRate] = useState(1.0);
  const [pitch, setPitch] = useState(1.0);
  const [volume, setVolume] = useState(1.0);
  const [wakeWord, setWakeWord] = useState(false);
  const [streaming, setStreaming] = useState(true);
  const [busy, setBusy] = useState(false);

  async function go() {
    onError(null);
    setBusy(true);
    try {
      await saveVoice({
        voice_name: voiceName,
        voice_rate: rate, voice_pitch: pitch, voice_volume: volume,
        wake_word_enabled: wakeWord,
        tts_streaming_enabled: streaming,
      });
      onDone();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">Voce di sistema e parametri TTS.</p>
      <Field label="Voce Piper (default: it_IT-paola-medium)" value={voiceName} onChange={setVoiceName} />
      <Field label={`Velocità ${rate.toFixed(2)}`} type="range" min={0.5} max={2.0} step={0.05} value={rate} onChange={(v) => setRate(Number(v))} />
      <Field label={`Tono ${pitch.toFixed(2)}`} type="range" min={0.0} max={2.0} step={0.05} value={pitch} onChange={(v) => setPitch(Number(v))} />
      <Field label={`Volume ${volume.toFixed(2)}`} type="range" min={0.0} max={1.0} step={0.05} value={volume} onChange={(v) => setVolume(Number(v))} />
      <CheckRow label="Attiva 'wake word' (CARA sempre in ascolto)" checked={wakeWord} onChange={setWakeWord} />
      <CheckRow label="Streaming TTS (audio inizia prima che il testo finisca)" checked={streaming} onChange={setStreaming} />
      <PrimaryButton onClick={go} disabled={busy} label={busy ? 'Salvo…' : 'Avanti →'} />
    </div>
  );
}


// ---------------------------------------------------------------------------
// Step 5 — LLM
// ---------------------------------------------------------------------------


function Step5LLM({
  onError,
  onDone,
}: {
  onError: (e: string | null) => void;
  onDone: () => void;
}) {
  const [quality, setQuality] = useState<'fast' | 'quality'>('fast');
  const [tone, setTone] = useState<'default' | 'privacy' | 'playful'>('default');
  const [maxTokens, setMaxTokens] = useState(512);
  const [systemPrompt, setSystemPrompt] = useState('');
  const [validation, setValidation] = useState(false);
  const [cognitive, setCognitive] = useState(false);
  const [busy, setBusy] = useState(false);

  async function go() {
    onError(null);
    setBusy(true);
    try {
      await saveLLM({
        quality_mode: quality,
        tone_preset: tone,
        max_new_tokens: maxTokens,
        system_prompt: systemPrompt || null,
        validation_enabled: validation,
        cognitive_mode: cognitive,
      });
      onDone();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">Modello AI e personalità.</p>
      <label className="block text-xs space-y-1">
        <span className="text-slate-400">Modello</span>
        <select value={quality} onChange={(e) => setQuality(e.target.value as 'fast' | 'quality')} className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm">
          <option value="fast">Veloce — Qwen 1.5B (raccomandato)</option>
          <option value="quality">Qualità — Qwen 3B (più lento, meno errori)</option>
        </select>
      </label>
      <label className="block text-xs space-y-1">
        <span className="text-slate-400">Stile</span>
        <select value={tone} onChange={(e) => setTone(e.target.value as 'default' | 'privacy' | 'playful')} className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm">
          <option value="default">Standard</option>
          <option value="privacy">Privacy (no profilo, no cronologia)</option>
          <option value="playful">Giocoso</option>
        </select>
      </label>
      <Field label={`Lunghezza max risposte: ${maxTokens} token`} type="range" min={64} max={1024} step={32} value={maxTokens} onChange={(v) => setMaxTokens(Number(v))} />
      <details className="rounded-lg bg-slate-800/40 border border-slate-700 p-3 text-xs">
        <summary className="cursor-pointer text-slate-300">Avanzate</summary>
        <div className="mt-2 space-y-2">
          <Field label="System prompt custom (vuoto = default)" value={systemPrompt} onChange={setSystemPrompt} textarea />
          <CheckRow label="Validation (richiede modello 3B+)" checked={validation} onChange={setValidation} />
          <CheckRow label="Cognitive mode" checked={cognitive} onChange={setCognitive} />
        </div>
      </details>
      <PrimaryButton onClick={go} disabled={busy} label={busy ? 'Salvo…' : 'Avanti →'} />
    </div>
  );
}


// ---------------------------------------------------------------------------
// Step 6 — Integrations (HA + VAPID + Telegram)
// ---------------------------------------------------------------------------


function Step6Integrations({
  onError,
  onDone,
}: {
  onError: (e: string | null) => void;
  onDone: () => void;
}) {
  const [haUrl, setHaUrl] = useState('http://172.31.0.1:8123');
  const [haToken, setHaToken] = useState('');
  const [haEnabled, setHaEnabled] = useState(false);
  const [haTestResult, setHaTestResult] = useState<string | null>(null);

  const [vapidGenerated, setVapidGenerated] = useState<string | null>(null);
  const [vapidSubject, setVapidSubject] = useState('');

  const [tgEnabled, setTgEnabled] = useState(false);
  const [tgToken, setTgToken] = useState('');
  const [tgChats, setTgChats] = useState('');

  const [busy, setBusy] = useState(false);

  async function testHA() {
    onError(null); setHaTestResult(null);
    try {
      const r = await testHomeAssistant({ url: haUrl, token: haToken });
      setHaTestResult(`Connessione OK: ${r.entity_count} entità trovate.`);
    } catch (e) {
      onError((e as Error).message);
    }
  }

  async function genVapid() {
    onError(null);
    try {
      const r = await generateVapid({ subject: vapidSubject || undefined });
      setVapidGenerated(r.public_key);
    } catch (e) {
      onError((e as Error).message);
    }
  }

  async function go() {
    onError(null); setBusy(true);
    try {
      await saveHomeAssistant({ enabled: haEnabled, url: haUrl, token: haToken || null });
      await saveTelegram({
        enabled: tgEnabled,
        bot_token: tgToken || null,
        allowed_chat_ids: tgChats.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean),
      });
      await completeIntegrations({});
      onDone();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">Integrazioni opzionali. Salta quelle che non usi.</p>

      {/* HomeAssistant */}
      <div className="rounded-xl bg-slate-800/40 border border-slate-700 p-4 space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">Home Assistant</h3>
          <CheckRow label="Abilita" checked={haEnabled} onChange={setHaEnabled} compact />
        </div>
        <Field label="URL" value={haUrl} onChange={setHaUrl} disabled={!haEnabled} />
        <Field label="Long-Lived Access Token" type="password" value={haToken} onChange={setHaToken} disabled={!haEnabled} />
        {haEnabled && (
          <button type="button" onClick={testHA} className="text-xs px-3 py-1 rounded-lg bg-slate-700 hover:bg-slate-600">
            Testa connessione
          </button>
        )}
        {haTestResult && <p className="text-xs text-emerald-300">{haTestResult}</p>}
      </div>

      {/* VAPID */}
      <div className="rounded-xl bg-slate-800/40 border border-slate-700 p-4 space-y-2">
        <h3 className="text-sm font-medium">Notifiche push (VAPID)</h3>
        <p className="text-xs text-slate-500">
          Una coppia di chiavi è necessaria per inviare promemoria push ai
          telefoni. Vengono generate sul server, mai esposte al frontend.
        </p>
        <Field label="Email per VAPID subject (opzionale)" value={vapidSubject} onChange={setVapidSubject} />
        <button type="button" onClick={genVapid} className="text-xs px-3 py-1 rounded-lg bg-slate-700 hover:bg-slate-600">
          Genera coppia di chiavi
        </button>
        {vapidGenerated && (
          <p className="text-xs text-emerald-300">
            ✓ Generate. Public key (primi 16 char): <code>{vapidGenerated.slice(0, 16)}…</code>
          </p>
        )}
      </div>

      {/* Telegram */}
      <div className="rounded-xl bg-slate-800/40 border border-slate-700 p-4 space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">Bot Telegram</h3>
          <CheckRow label="Abilita" checked={tgEnabled} onChange={setTgEnabled} compact />
        </div>
        <Field label="Bot token" type="password" value={tgToken} onChange={setTgToken} disabled={!tgEnabled} />
        <Field label="Chat ID consentite (separate da virgola)" value={tgChats} onChange={setTgChats} disabled={!tgEnabled} />
      </div>

      <PrimaryButton onClick={go} disabled={busy} label={busy ? 'Salvo…' : 'Avanti →'} />
    </div>
  );
}


// ---------------------------------------------------------------------------
// Step 7 — Google + Cloud
// ---------------------------------------------------------------------------


function Step7GoogleCloud({
  onError,
  onDone,
}: {
  onError: (e: string | null) => void;
  onDone: () => void;
}) {
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [genKey, setGenKey] = useState(true);

  const [cloudEnabled, setCloudEnabled] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [skillAuthor, setSkillAuthor] = useState(false);
  const [cloudOk, setCloudOk] = useState<string | null>(null);

  const [busy, setBusy] = useState(false);

  async function testApiKey() {
    onError(null); setCloudOk(null);
    if (!apiKey) {
      onError('Inserisci una API key prima di testare');
      return;
    }
    try {
      const r = await testCloud({ api_key: apiKey });
      setCloudOk(`API key valida (${r.input_tokens} token di test).`);
    } catch (e) {
      onError((e as Error).message);
    }
  }

  async function go() {
    onError(null); setBusy(true);
    try {
      if (clientId || clientSecret || genKey) {
        await saveGoogle({
          client_id: clientId || null,
          client_secret: clientSecret || null,
          generate_encryption_key: genKey,
        });
      }
      await saveCloud({
        enabled: cloudEnabled,
        api_key: apiKey || null,
        skill_author_enabled: cloudEnabled && skillAuthor,
      });
      onDone();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">Google Calendar/Gmail e Cloud LLM (entrambe opzionali).</p>

      <div className="rounded-xl bg-slate-800/40 border border-slate-700 p-4 space-y-2">
        <h3 className="text-sm font-medium">Google Calendar + Gmail</h3>
        <p className="text-xs text-slate-500">
          Crea un OAuth client su{' '}
          <a className="underline text-emerald-300" target="_blank" rel="noreferrer" href="https://console.cloud.google.com/apis/credentials">Google Cloud Console</a>{' '}
          (tipo "Web application", redirect URI{' '}
          <code className="text-emerald-300">https://192.168.1.23:8455/api/v1/oauth/google/callback</code>).
        </p>
        <Field label="Client ID" value={clientId} onChange={setClientId} />
        <Field label="Client Secret" type="password" value={clientSecret} onChange={setClientSecret} />
        <CheckRow
          label="Genera chiave di cifratura per i token (consigliato se non c'è)"
          checked={genKey} onChange={setGenKey}
        />
      </div>

      <div className="rounded-xl bg-slate-800/40 border border-slate-700 p-4 space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">Cloud LLM (Anthropic Haiku)</h3>
          <CheckRow label="Abilita" checked={cloudEnabled} onChange={setCloudEnabled} compact />
        </div>
        <p className="text-xs text-amber-300/80">
          ⚠ Sperimentale + a pagamento. Il modello locale 1.5B basta per la
          casa. Abilita solo se vuoi ragionamento complesso (validation,
          email NLU avanzata, skill author).
        </p>
        <Field label="API key Anthropic" type="password" value={apiKey} onChange={setApiKey} disabled={!cloudEnabled} />
        {cloudEnabled && (
          <button type="button" onClick={testApiKey} className="text-xs px-3 py-1 rounded-lg bg-slate-700 hover:bg-slate-600">
            Testa API key
          </button>
        )}
        {cloudOk && <p className="text-xs text-emerald-300">{cloudOk}</p>}
        <CheckRow
          label="Abilita Skill Author (richiede cloud LLM)"
          checked={skillAuthor} onChange={setSkillAuthor}
        />
      </div>

      <PrimaryButton onClick={go} disabled={busy} label={busy ? 'Salvo…' : 'Avanti →'} />
    </div>
  );
}


// ---------------------------------------------------------------------------
// Step 8 — Feature flags
// ---------------------------------------------------------------------------


function Step8FeatureFlags({
  onError,
  onDone,
}: {
  onError: (e: string | null) => void;
  onDone: () => void;
}) {
  const [flags, setFlags] = useState({
    internet_enabled: false,
    news_enabled: false,
    radio_enabled: false,
    cda_enabled: true,
    cda_safe_search_for_minors: true,
    proactive_suggestions_enabled: false,
    habit_learning_enabled: false,
    skill_dispatcher_tier2_enabled: true,
    skill_dispatcher_tier3_enabled: false,
    voice_recognition_enabled: true,
  });

  const [busy, setBusy] = useState(false);

  function set<K extends keyof typeof flags>(k: K, v: boolean) {
    setFlags((prev) => ({ ...prev, [k]: v }));
  }

  async function go() {
    onError(null); setBusy(true);
    try {
      await saveFeatureFlags(flags);
      onDone();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const rows: { key: keyof typeof flags; label: string; help?: string }[] = useMemo(() => [
    { key: 'internet_enabled',         label: 'Accesso internet',          help: 'Master switch per news/radio/web. OFF = CARA totalmente offline.' },
    { key: 'news_enabled',             label: 'News',                       help: 'Richiede internet abilitato.' },
    { key: 'radio_enabled',            label: 'Radio',                      help: 'Richiede internet abilitato.' },
    { key: 'cda_enabled',              label: 'Discovery dinamica',         help: 'CARA cerca contenuti nuovi nel web (richiede internet).' },
    { key: 'cda_safe_search_for_minors',label: 'Safe search per minori',     help: 'Sempre attivo per teen/child/elder.' },
    { key: 'proactive_suggestions_enabled', label: 'Suggerimenti proattivi', help: 'Avvia silente — abilita quando ti fidi del comportamento.' },
    { key: 'habit_learning_enabled',   label: 'Apprendimento abitudini',    help: 'Suggerisce automaticamente da pattern ricorrenti.' },
    { key: 'skill_dispatcher_tier2_enabled', label: 'Skill matching cosine', help: 'Matching skill via similarità semantica.' },
    { key: 'skill_dispatcher_tier3_enabled', label: 'Skill matching LLM',    help: 'Più costoso (~1s per messaggio) ma più flessibile.' },
    { key: 'voice_recognition_enabled', label: 'Riconoscimento vocale',     help: 'Web Speech in browser per dettatura.' },
  ], []);

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">Privacy by default — abilita solo ciò che ti serve.</p>
      <ul className="space-y-1.5">
        {rows.map((r) => (
          <li key={r.key} className="rounded-lg bg-slate-800/50 border border-slate-700 p-3">
            <CheckRow label={r.label} checked={flags[r.key]} onChange={(v) => set(r.key, v)} />
            {r.help && <p className="text-[11px] text-slate-500 mt-1 pl-7">{r.help}</p>}
          </li>
        ))}
      </ul>
      <PrimaryButton onClick={go} disabled={busy} label={busy ? 'Concludo…' : 'Termina configurazione'} />
    </div>
  );
}


// ---------------------------------------------------------------------------
// Done
// ---------------------------------------------------------------------------


function CompleteScreen({ onContinue }: { onContinue: () => void }) {
  return (
    <main className="min-h-dvh flex items-center justify-center bg-slate-900 text-slate-100 p-6">
      <div className="max-w-md text-center space-y-4">
        <p className="text-5xl">🌱</p>
        <h1 className="text-2xl font-light">CARA è pronta.</h1>
        <p className="text-sm text-slate-400">
          Configurazione salvata. Puoi tornare a riconfigurare in qualsiasi
          momento da{' '}
          <code className="text-emerald-300">/admin/setup</code>.
        </p>
        <button
          type="button" onClick={onContinue}
          className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-sm font-medium"
        >
          Vai a casa →
        </button>
      </div>
    </main>
  );
}


// ---------------------------------------------------------------------------
// Shared input primitives
// ---------------------------------------------------------------------------


interface FieldProps {
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
  disabled?: boolean;
  textarea?: boolean;
  min?: number;
  max?: number;
  step?: number;
}


function Field({
  label, value, onChange, type, required, disabled, textarea, min, max, step,
}: FieldProps) {
  return (
    <label className="block space-y-1 text-xs">
      <span className="text-slate-400">{label}</span>
      {textarea ? (
        <textarea
          value={value as string}
          onChange={(e) => onChange(e.target.value)}
          required={required} disabled={disabled} rows={3}
          className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm disabled:opacity-50"
        />
      ) : (
        <input
          type={type ?? 'text'} value={value}
          onChange={(e) => onChange(e.target.value)}
          required={required} disabled={disabled}
          min={min} max={max} step={step}
          className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm disabled:opacity-50"
        />
      )}
    </label>
  );
}


function CheckRow({
  label, checked, onChange, compact,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  compact?: boolean;
}) {
  return (
    <label className={`flex items-center gap-2 ${compact ? 'text-[11px]' : 'text-xs'}`}>
      <input
        type="checkbox" checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-emerald-500"
      />
      <span className={compact ? 'text-slate-400' : 'text-slate-200'}>{label}</span>
    </label>
  );
}


function PrimaryButton({
  onClick, disabled, label,
}: {
  onClick: () => void;
  disabled: boolean;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="w-full rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-4 py-2.5 text-sm font-medium"
    >
      {label}
    </button>
  );
}


// Re-export the reset hook for the admin page.
export { resetSetup };
