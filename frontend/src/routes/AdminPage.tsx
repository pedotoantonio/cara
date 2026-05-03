/**
 * Admin control panel — feature flags + AI behaviour tuning + audit log.
 * Gated to admins only (renders nothing if `user.is_admin` is false).
 */

import { useEffect, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';

import {
  getAdminAudit,
  getAdminSettings,
  patchAdminSettings,
  type AuditEntry,
} from '../api/admin';
import type { User } from '../api/auth';
import { listVoices, setVoiceConfig, speak, ttsAvailable } from '../lib/speech';
import { listPiperVoices, type PiperVoice } from '../lib/piperTts';

const FEATURE_FLAGS: Array<{ key: string; label: string; help: string }> = [
  { key: 'internet_enabled', label: 'Accesso internet', help: 'Master switch per news/radio/web' },
  { key: 'news_enabled', label: 'News (RSS)', help: 'Pagina e tool get_news' },
  { key: 'radio_enabled', label: 'Radio streaming', help: 'Pagina e tool play_radio' },
  { key: 'video_enabled', label: 'Video', help: 'Riservato (non implementato)' },
  { key: 'habit_learning_enabled', label: 'Autoapprendimento abitudini', help: 'Riservato (Estensione 1)' },
  { key: 'proactive_suggestions_enabled', label: 'Suggerimenti proattivi', help: 'Riservato' },
  { key: 'telegram_bot_enabled', label: 'Telegram bot', help: 'Richiede CARA_TELEGRAM_BOT_TOKEN' },
  { key: 'facial_recognition_enabled', label: 'Riconoscimento facciale', help: 'Integrazione frigate-faces' },
  { key: 'voice_recognition_enabled', label: 'Riconoscimento vocale', help: 'STT browser-side' },
  { key: 'smart_home_enabled', label: 'Smart home', help: 'Riservato' },
  { key: 'push_notifications_enabled', label: 'Notifiche push PWA', help: 'Riservato' },
  { key: 'cloud_llm_enabled', label: 'LLM cloud (fallback)', help: 'Riservato' },
  { key: 'validation_enabled', label: 'Validazione risposte (self-critique)', help: 'Raddoppia latenza' },
  { key: 'cognitive_mode', label: 'Cognitive mode (prompt esteso)', help: 'Per modelli 3B+' },
  { key: 'cda_enabled', label: 'Content Discovery Agent', help: 'Tool [discover] per trovare contenuti su internet' },
  { key: 'cda_replace_legacy_pages', label: 'Radio/News dalla KB', help: 'Pagine leggono da cda_content_items invece dei feed hardcoded' },
  { key: 'cda_ytdlp_youtube_enabled', label: 'yt-dlp per video YouTube', help: 'Estrae stream invece di usare embed (zona grigia ToS)' },
  { key: 'cda_safe_search_for_minors', label: 'Safe Search per minori', help: 'Forza filtro nei profili child/teen' },
];

const PROMPT_FIELDS: Array<{
  key: string;
  label: string;
  rows: number;
  help: string;
}> = [
  {
    key: 'llm_system_prompt',
    label: 'System prompt CARA',
    rows: 18,
    help: "La 'persona' di CARA. Richiede una nuova chat per attivare il cambio (le conversazioni esistenti hanno il prompt seedato in DB).",
  },
  {
    key: 'llm_validation_prompt',
    label: 'Prompt di validazione (self-critique)',
    rows: 12,
    help: 'Usato dal validatore quando validation_enabled è ON. Effetto immediato.',
  },
  {
    key: 'llm_cognitive_prompt',
    label: 'Cognitive prompt (esteso)',
    rows: 12,
    help: 'Anteposto al system prompt quando cognitive_mode è ON.',
  },
];

const NUMERIC_FIELDS: Array<{ key: string; label: string; min: number; max: number; help: string }> = [
  {
    key: 'llm_max_new_tokens',
    label: 'Max token risposta default',
    min: 50,
    max: 2048,
    help: '900 è un buon default. Più alto = risposte più lunghe ma più lente.',
  },
  {
    key: 'llm_validation_max_tokens',
    label: 'Max token per la validazione',
    min: 30,
    max: 600,
    help: '160 di default. Solo se validation_enabled è ON.',
  },
];

interface VoiceDraft {
  name: string;
  rate: number;
  pitch: number;
  volume: number;
}

const VOICE_DEFAULT: VoiceDraft = { name: '', rate: 1, pitch: 1, volume: 1 };

export function AdminPage() {
  const { user } = useOutletContext<{ user: User }>();
  const navigate = useNavigate();
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [draftPrompts, setDraftPrompts] = useState<Record<string, string>>({});
  const [draftNumbers, setDraftNumbers] = useState<Record<string, string>>({});
  const [voice, setVoice] = useState<VoiceDraft>(VOICE_DEFAULT);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // Browser voices available on this device — used as suggestions for the
  // "voce del browser" engine. Loaded asynchronously by the browser.
  const [availableVoices, setAvailableVoices] = useState<SpeechSynthesisVoice[]>([]);
  useEffect(() => {
    if (!ttsAvailable() || !('speechSynthesis' in window)) return;
    setAvailableVoices(listVoices());
    const sy = window.speechSynthesis;
    const onChange = () => setAvailableVoices(listVoices());
    const prev = sy.onvoiceschanged;
    sy.onvoiceschanged = (...args) => {
      onChange();
      if (typeof prev === 'function') (prev as (this: SpeechSynthesis, ev: Event) => unknown).call(sy, ...args);
    };
    return () => {
      sy.onvoiceschanged = prev;
    };
  }, []);

  // Server-side Piper voices catalog (the "Voce di CARA" engine).
  const [piperVoices, setPiperVoices] = useState<PiperVoice[]>([]);
  useEffect(() => {
    listPiperVoices()
      .then(setPiperVoices)
      .catch(() => setPiperVoices([]));
  }, []);

  useEffect(() => {
    if (!user.is_admin) navigate('/chat', { replace: true });
  }, [user, navigate]);

  async function refresh() {
    try {
      const [s, a] = await Promise.all([getAdminSettings(), getAdminAudit(50)]);
      setSettings(s);
      setAudit(a);
      setDraftPrompts({
        llm_system_prompt: (s.llm_system_prompt as string) ?? '',
        llm_validation_prompt: (s.llm_validation_prompt as string) ?? '',
        llm_cognitive_prompt: (s.llm_cognitive_prompt as string) ?? '',
      });
      setDraftNumbers({
        llm_max_new_tokens: String(s.llm_max_new_tokens ?? ''),
        llm_validation_max_tokens: String(s.llm_validation_max_tokens ?? ''),
      });
      setVoice({
        name: typeof s.voice_name === 'string' ? s.voice_name : '',
        rate: typeof s.voice_rate === 'number' ? s.voice_rate : 1,
        pitch: typeof s.voice_pitch === 'number' ? s.voice_pitch : 1,
        volume: typeof s.voice_volume === 'number' ? s.voice_volume : 1,
      });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function patch(values: Record<string, unknown>, scope: string) {
    setSaving(scope);
    setMsg(null);
    try {
      const next = await patchAdminSettings(values);
      setSettings(next);
      setMsg({ ok: true, text: 'Salvato.' });
      // Refresh audit so the new entry appears.
      getAdminAudit(50).then(setAudit).catch(() => undefined);
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setSaving(null);
    }
  }

  async function toggleFlag(key: string, value: boolean) {
    await patch({ [key]: value }, key);
  }

  async function savePrompt(key: string) {
    const v = draftPrompts[key];
    await patch({ [key]: v.trim() ? v : null }, key);
  }

  async function saveNumber(key: string) {
    const raw = draftNumbers[key];
    if (!raw.trim()) {
      await patch({ [key]: null }, key);
      return;
    }
    const n = Number(raw);
    if (!Number.isFinite(n)) {
      setMsg({ ok: false, text: `Valore non numerico per ${key}` });
      return;
    }
    await patch({ [key]: n }, key);
  }

  async function saveVoice() {
    // Reset-to-default semantics: if a slider is at 1.0 and the name field
    // is blank, send null so the backend forgets the override.
    const payload = {
      voice_name: voice.name.trim() ? voice.name.trim() : null,
      voice_rate: voice.rate === 1 ? null : voice.rate,
      voice_pitch: voice.pitch === 1 ? null : voice.pitch,
      voice_volume: voice.volume === 1 ? null : voice.volume,
    };
    await patch(payload, 'voice');
    // Apply locally immediately so subsequent calls to `speak()` use the
    // new values without an app reload.
    setVoiceConfig({
      name: payload.voice_name,
      rate: payload.voice_rate,
      pitch: payload.voice_pitch,
      volume: payload.voice_volume,
    });
  }

  function previewVoice() {
    speak('Ciao, sono CARA. Sento che la mia voce ti suona bene così?', {
      lang: 'it',
      rate: voice.rate,
      pitch: voice.pitch,
      volume: voice.volume,
      voiceName: voice.name.trim() || undefined,
    });
  }

  // Quickly preview a single Piper voice from the catalog (without writing
  // it to the global "name" field — handy to compare voices side by side).
  function previewPiperVoice(piperId: string) {
    speak('Ciao, sono CARA. Senti come suono?', {
      lang: 'it',
      rate: voice.rate,
      pitch: voice.pitch,
      volume: voice.volume,
      voiceName: piperId,
    });
  }

  function resetVoice() {
    setVoice(VOICE_DEFAULT);
  }

  if (loading) {
    return (
      <main className="flex-1 p-6 text-slate-500 text-sm bg-slate-900">Carico…</main>
    );
  }

  return (
    <main className="flex-1 overflow-y-auto bg-slate-900 text-slate-100">
      <div className="max-w-3xl mx-auto p-4 md:p-6 space-y-6">
        <header>
          <h1 className="text-xl font-medium">Pannello amministratore</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Configurazione comportamento AI, integrazioni e cronologia azioni.
          </p>
        </header>

        {msg && (
          <div
            className={`rounded-xl px-3 py-2 text-xs border ${
              msg.ok
                ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-200'
                : 'bg-rose-500/10 border-rose-500/40 text-rose-200'
            }`}
          >
            {msg.text}
          </div>
        )}

        {/* Feature flags */}
        <section className="rounded-2xl bg-slate-800/60 border border-slate-700 p-5 space-y-3">
          <h2 className="text-sm font-medium">Funzionalità</h2>
          <p className="text-xs text-slate-500">Effetto immediato. Toggle salvati in DB e auditati.</p>
          <div className="grid sm:grid-cols-2 gap-2">
            {FEATURE_FLAGS.map((f) => {
              const value = Boolean(settings[f.key]);
              return (
                <label
                  key={f.key}
                  className="flex items-start gap-2 rounded-lg bg-slate-900/40 border border-slate-700/40 px-3 py-2 cursor-pointer text-xs"
                  title={f.help}
                >
                  <input
                    type="checkbox"
                    checked={value}
                    disabled={saving === f.key}
                    onChange={(e) => toggleFlag(f.key, e.target.checked)}
                    className="mt-0.5 accent-emerald-500"
                  />
                  <span>
                    <p className="text-slate-100">{f.label}</p>
                    <p className="text-slate-500">{f.help}</p>
                  </span>
                </label>
              );
            })}
          </div>
        </section>

        {/* LLM quality mode (Lumo-inspired Q4/Q6 dual mode) */}
        <section className="rounded-2xl bg-slate-800/60 border border-slate-700 p-5 space-y-3">
          <h2 className="text-sm font-medium">Modello LLM (qualità vs velocità)</h2>
          <p className="text-xs text-slate-500">
            Lo switch è hot-swap a runtime: il primo cambio richiede ~10 s
            per scaricare e ricaricare i pesi sul NPU. Da quel momento il
            modello scelto resta caricato.
          </p>
          <div className="grid sm:grid-cols-2 gap-2">
            {(
              [
                {
                  v: 'fast',
                  label: '⚡ Veloce — Qwen2.5 1.5B',
                  desc: '~9 tok/s, TTFT 0.3 s. Default, ottimo per chat e comandi rapidi.',
                },
                {
                  v: 'quality',
                  label: '🎯 Qualità — Qwen2.5 3B',
                  desc: '~4 tok/s, TTFT 0.7 s. Meno hallucinazione, instruction-following migliore.',
                },
              ] as const
            ).map((q) => {
              const active = (settings.llm_quality_mode ?? 'fast') === q.v;
              return (
                <button
                  key={q.v}
                  type="button"
                  onClick={() => patch({ llm_quality_mode: q.v }, 'llm_quality_mode')}
                  disabled={saving === 'llm_quality_mode'}
                  className={`text-left rounded-lg border px-3 py-2 text-xs transition-colors ${
                    active
                      ? 'bg-emerald-600/20 border-emerald-500 text-emerald-100'
                      : 'bg-slate-900/40 border-slate-700/40 text-slate-300 hover:bg-slate-700/40'
                  }`}
                >
                  <p className="font-medium">{q.label}</p>
                  <p className="text-slate-500 mt-0.5">{q.desc}</p>
                </button>
              );
            })}
          </div>
        </section>

        {/* Tone preset (Lumo-inspired) */}
        <section className="rounded-2xl bg-slate-800/60 border border-slate-700 p-5 space-y-3">
          <h2 className="text-sm font-medium">Tono di CARA</h2>
          <p className="text-xs text-slate-500">
            Aggiunge una direttiva al system prompt e (in modalità privacy)
            esclude la cronologia conversazione dal prompt LLM. Effetto immediato.
          </p>
          <div className="grid sm:grid-cols-3 gap-2">
            {(
              [
                {
                  v: 'default',
                  label: 'Default',
                  desc: 'Persona standard con cronologia e profilo utente.',
                },
                {
                  v: 'privacy',
                  label: 'Privacy',
                  desc: 'Niente nome utente, niente cronologia. Solo turno corrente.',
                },
                {
                  v: 'playful',
                  label: 'Scherzoso',
                  desc: 'Tono più leggero e ironico. Senza esagerare.',
                },
              ] as const
            ).map((t) => {
              const active = (settings.tone_preset ?? 'default') === t.v;
              return (
                <button
                  key={t.v}
                  type="button"
                  onClick={() => patch({ tone_preset: t.v }, 'tone_preset')}
                  disabled={saving === 'tone_preset'}
                  className={`text-left rounded-lg border px-3 py-2 text-xs transition-colors ${
                    active
                      ? 'bg-emerald-600/20 border-emerald-500 text-emerald-100'
                      : 'bg-slate-900/40 border-slate-700/40 text-slate-300 hover:bg-slate-700/40'
                  }`}
                >
                  <p className="font-medium">{t.label}</p>
                  <p className="text-slate-500 mt-0.5">{t.desc}</p>
                </button>
              );
            })}
          </div>
        </section>

        {/* Numeric tunables */}
        <section className="rounded-2xl bg-slate-800/60 border border-slate-700 p-5 space-y-3">
          <h2 className="text-sm font-medium">Parametri numerici</h2>
          {NUMERIC_FIELDS.map((f) => (
            <div key={f.key} className="space-y-1">
              <label className="block text-xs text-slate-400">
                {f.label}{' '}
                <span className="text-slate-600">
                  ({f.min}–{f.max}, vuoto = default da .env)
                </span>
              </label>
              <div className="flex gap-2">
                <input
                  type="number"
                  min={f.min}
                  max={f.max}
                  value={draftNumbers[f.key] ?? ''}
                  onChange={(e) =>
                    setDraftNumbers({ ...draftNumbers, [f.key]: e.target.value })
                  }
                  className="flex-1 rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                />
                <button
                  type="button"
                  onClick={() => saveNumber(f.key)}
                  disabled={saving === f.key}
                  className="rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-4 py-2 text-sm font-medium"
                >
                  Salva
                </button>
              </div>
              <p className="text-xs text-slate-500">{f.help}</p>
            </div>
          ))}
        </section>

        {/* Voice (TTS) tuning */}
        <section className="rounded-2xl bg-slate-800/60 border border-slate-700 p-5 space-y-4">
          <header className="space-y-1">
            <h2 className="text-sm font-medium">Voce di CARA</h2>
            <p className="text-xs text-slate-500">
              CARA può parlare in due modi: <strong className="text-slate-300">"voce di CARA"</strong>{' '}
              (Piper sul server, stessa su tutti i dispositivi della famiglia, italiana nativa) oppure
              <strong className="text-slate-300">"voce del browser"</strong> (es. Paola di iPhone, qualità
              top quando il dispositivo ce l'ha). Ogni utente sceglie quale usare in <em>Impostazioni</em>;
              qui sotto puoi configurare le preferenze di default.
            </p>
          </header>

          {/* Piper voice catalog */}
          <div className="space-y-2">
            <h3 className="text-xs font-medium text-slate-300 uppercase tracking-wide">
              "Voce di CARA" (Piper, server)
            </h3>
            {piperVoices.length === 0 ? (
              <p className="text-xs text-slate-500">
                Catalogo Piper non disponibile (TTS server non avviato o ancora in caricamento).
              </p>
            ) : (
              <div className="space-y-2">
                <p className="text-[11px] text-slate-500">
                  Le voci si scaricano automaticamente al primo utilizzo (~20–60 MB ciascuna). Default
                  configurato in <code className="text-emerald-300">.env</code> con{' '}
                  <code className="text-emerald-300">TTS_DEFAULT_VOICE</code>.
                </p>
                <ul className="space-y-1">
                  {piperVoices.map((pv) => (
                    <li
                      key={pv.id}
                      className="flex items-center gap-2 rounded-lg bg-slate-900/40 border border-slate-700/40 px-3 py-2 text-xs"
                    >
                      <span className="flex-1 min-w-0">
                        <span className="text-slate-100">{pv.display_name}</span>{' '}
                        <span className="text-slate-500">
                          {pv.locale} · {pv.gender ?? '—'} · {pv.quality}
                          {pv.size_mb ? ` · ${pv.size_mb} MB` : ''} · {pv.license}
                        </span>
                        {pv.description && (
                          <span className="block text-slate-600">{pv.description}</span>
                        )}
                      </span>
                      <button
                        type="button"
                        onClick={() => previewPiperVoice(pv.id)}
                        className="rounded-lg bg-slate-900 hover:bg-slate-700 border border-slate-700 px-2 py-1"
                      >
                        ▶
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Browser voice preference */}
          <div className="space-y-1 pt-2 border-t border-slate-700/50">
            <h3 className="text-xs font-medium text-slate-300 uppercase tracking-wide">
              "Voce del browser" — voce preferita
            </h3>
            <p className="text-[11px] text-slate-500">
              Suggerimento usato dai client che hanno scelto la voce del browser. Su iPhone/iPad
              "Paola" è la voce italiana premium.
            </p>
            <input
              type="text"
              list="cara-admin-voice-list"
              value={voice.name}
              onChange={(e) => setVoice({ ...voice, name: e.target.value })}
              placeholder="es. Paola (vuoto = scelta automatica)"
              className="w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
            />
            <datalist id="cara-admin-voice-list">
              {availableVoices.map((v) => (
                <option key={`${v.name}|${v.lang}`} value={v.name}>
                  {v.lang}
                  {v.localService ? ' · locale' : ' · cloud'}
                </option>
              ))}
            </datalist>
            {availableVoices.length > 0 && (
              <p className="text-[11px] text-slate-600">
                {availableVoices.length} voci installate su questo browser
                {availableVoices.some((v) => v.lang.toLowerCase().startsWith('it'))
                  ? ' · italiane disponibili: '
                  : ' · nessuna voce italiana — installala dalle impostazioni di sistema'}
                {availableVoices
                  .filter((v) => v.lang.toLowerCase().startsWith('it'))
                  .map((v) => v.name)
                  .join(', ')}
              </p>
            )}
          </div>

          <div className="grid sm:grid-cols-3 gap-4">
            <label className="block text-xs text-slate-400 space-y-1">
              <span>
                Velocità: <span className="text-slate-200">{voice.rate.toFixed(2)}×</span>
              </span>
              <input
                type="range"
                min={0.5}
                max={2}
                step={0.05}
                value={voice.rate}
                onChange={(e) => setVoice({ ...voice, rate: Number(e.target.value) })}
                className="w-full accent-emerald-500"
              />
              <span className="block text-[11px] text-slate-600">0.5 lenta · 2 veloce</span>
            </label>
            <label className="block text-xs text-slate-400 space-y-1">
              <span>
                Tonalità: <span className="text-slate-200">{voice.pitch.toFixed(2)}</span>
              </span>
              <input
                type="range"
                min={0}
                max={2}
                step={0.05}
                value={voice.pitch}
                onChange={(e) => setVoice({ ...voice, pitch: Number(e.target.value) })}
                className="w-full accent-emerald-500"
              />
              <span className="block text-[11px] text-slate-600">0 grave · 2 acuta</span>
            </label>
            <label className="block text-xs text-slate-400 space-y-1">
              <span>
                Volume: <span className="text-slate-200">{Math.round(voice.volume * 100)}%</span>
              </span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={voice.volume}
                onChange={(e) => setVoice({ ...voice, volume: Number(e.target.value) })}
                className="w-full accent-emerald-500"
              />
              <span className="block text-[11px] text-slate-600">0 muto · 100% pieno</span>
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button
              type="button"
              onClick={previewVoice}
              disabled={!ttsAvailable()}
              className="rounded-xl bg-slate-900 hover:bg-slate-700 border border-slate-700 disabled:opacity-40 px-3 py-2 text-sm"
            >
              ▶ Anteprima
            </button>
            <button
              type="button"
              onClick={resetVoice}
              className="rounded-xl bg-slate-900 hover:bg-slate-700 border border-slate-700 px-3 py-2 text-sm"
            >
              Ripristina default
            </button>
            <button
              type="button"
              onClick={saveVoice}
              disabled={saving === 'voice'}
              className="rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-4 py-2 text-sm font-medium ml-auto"
            >
              {saving === 'voice' ? 'Salvo…' : 'Salva voce'}
            </button>
          </div>
          <p className="text-[11px] text-slate-600">
            L'anteprima usa i valori dei cursori (anche prima di salvare). I valori salvati vengono
            applicati a chi apre CARA, all'avvio dell'app.
          </p>
        </section>

        {/* Prompt editors */}
        <section className="rounded-2xl bg-slate-800/60 border border-slate-700 p-5 space-y-4">
          <h2 className="text-sm font-medium">Prompt (testo)</h2>
          {PROMPT_FIELDS.map((f) => (
            <div key={f.key} className="space-y-1">
              <label className="block text-xs text-slate-400">{f.label}</label>
              <textarea
                rows={f.rows}
                value={draftPrompts[f.key] ?? ''}
                onChange={(e) =>
                  setDraftPrompts({ ...draftPrompts, [f.key]: e.target.value })
                }
                placeholder="(vuoto: usa il default da .env)"
                className="w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
              />
              <div className="flex gap-2 items-center">
                <button
                  type="button"
                  onClick={() => savePrompt(f.key)}
                  disabled={saving === f.key}
                  className="rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-4 py-2 text-sm font-medium"
                >
                  Salva {f.label}
                </button>
                <p className="text-xs text-slate-500 flex-1">{f.help}</p>
              </div>
            </div>
          ))}
        </section>

        {/* Audit log */}
        <section className="rounded-2xl bg-slate-800/40 border border-slate-700/60 p-5 space-y-2">
          <h2 className="text-sm font-medium">Cronologia azioni admin</h2>
          {audit.length === 0 ? (
            <p className="text-xs text-slate-500">Nessuna azione registrata.</p>
          ) : (
            <ul className="text-xs space-y-1 max-h-72 overflow-y-auto">
              {audit.map((e) => (
                <li key={e.id} className="flex gap-2 text-slate-400">
                  <span className="text-slate-500 shrink-0">
                    {new Date(e.created_at).toLocaleString('it-IT', {
                      day: '2-digit',
                      month: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                  <span className="text-emerald-400">{e.action}</span>
                  <span className="text-slate-300 truncate">
                    {e.actor_email ?? '—'}{' '}
                    {e.detail && <span className="text-slate-500">{JSON.stringify(e.detail).slice(0, 80)}</span>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  );
}
