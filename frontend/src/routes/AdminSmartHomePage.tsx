// /admin/smart-home — connection config + entity browser + voice mapping test.

import { useEffect, useMemo, useState } from 'react';

import { authFetch } from '../api/auth';
import {
  Entity,
  HealthStatus,
  callService,
  getHealth,
  listEntities,
  resolveUtterance,
} from '../api/smarthome';
import {
  Badge,
  BottomSheet,
  Button,
  Card,
  CardSubtitle,
  CardTitle,
  Field,
  Input,
  cn,
  useToast,
} from '../design';

interface SettingsBlob {
  'smarthome.enabled'?: boolean;
  'smarthome.ha_url'?: string;
  'smarthome.ha_token'?: string;
}

const API = '/api/v1';

async function getSettings(): Promise<SettingsBlob> {
  const r = await authFetch(`${API}/admin/settings`);
  if (!r.ok) throw new Error(`settings: ${r.status}`);
  return r.json();
}

async function patchSettings(diff: Record<string, unknown>): Promise<void> {
  const r = await authFetch(`${API}/admin/settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings: diff }),
  });
  if (!r.ok) throw new Error(`settings patch: ${r.status}`);
}

function deriveDomainGroup(domain: string): string {
  const map: Record<string, string> = {
    light: 'Luci',
    switch: 'Interruttori',
    cover: 'Tapparelle / serrande',
    climate: 'Termostati',
    sensor: 'Sensori',
    binary_sensor: 'Sensori binari',
    lock: 'Serrature',
    alarm_control_panel: 'Allarmi',
    media_player: 'Media',
    scene: 'Scene',
    camera: 'Telecamere',
    person: 'Persone',
    weather: 'Meteo',
  };
  return map[domain] ?? domain;
}

export function AdminSmartHomePage() {
  const toast = useToast();
  const [enabled, setEnabled] = useState(false);
  const [haUrl, setHaUrl] = useState('');
  const [haToken, setHaToken] = useState('');
  const [savingConfig, setSavingConfig] = useState(false);

  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [entities, setEntities] = useState<Entity[] | null>(null);
  const [domainFilter, setDomainFilter] = useState<string>('all');

  const [voiceTest, setVoiceTest] = useState('');
  const [voiceResult, setVoiceResult] = useState<string | null>(null);
  const [voiceBusy, setVoiceBusy] = useState(false);

  const [serviceOpen, setServiceOpen] = useState(false);
  const [serviceTarget, setServiceTarget] = useState<Entity | null>(null);

  // Initial load.
  useEffect(() => {
    void (async () => {
      try {
        const s = await getSettings();
        setEnabled(Boolean(s['smarthome.enabled']));
        setHaUrl(String(s['smarthome.ha_url'] ?? ''));
        // Token shown obfuscated unless freshly typed.
        setHaToken(s['smarthome.ha_token'] ? '••••••••••••' : '');
      } catch {/* best effort */}
    })();
  }, []);

  // Live data when enabled + URL+token are set.
  useEffect(() => {
    if (!enabled) return;
    void (async () => {
      try { setHealth(await getHealth()); } catch { setHealth(null); }
      try { setEntities(await listEntities()); } catch { setEntities([]); }
    })();
  }, [enabled]);

  async function saveConfig() {
    setSavingConfig(true);
    try {
      const diff: Record<string, unknown> = {
        'smarthome.enabled': enabled,
        'smarthome.ha_url': haUrl.trim(),
      };
      if (haToken && haToken !== '••••••••••••') {
        diff['smarthome.ha_token'] = haToken.trim();
      }
      await patchSettings(diff);
      toast.push({ kind: 'ok', title: 'Configurazione salvata' });
      // Refresh health + entities.
      try { setHealth(await getHealth()); } catch { setHealth(null); }
      try { setEntities(await listEntities()); } catch { setEntities([]); }
    } catch (e) {
      toast.push({
        kind: 'alert',
        title: 'Salvataggio fallito',
        body: (e as Error).message,
      });
    } finally {
      setSavingConfig(false);
    }
  }

  async function runVoiceTest() {
    if (!voiceTest.trim() || voiceBusy) return;
    setVoiceBusy(true);
    setVoiceResult(null);
    try {
      const r = await resolveUtterance(voiceTest);
      const parts: string[] = [];
      if (!r.matched_intent) {
        parts.push('Nessun intent riconosciuto.');
      } else {
        parts.push(`Action: ${r.action}`);
        parts.push(`Target: "${r.target_phrase}"`);
        if (r.value) parts.push(`Valore: ${r.value}`);
        if (r.candidates && r.candidates.length > 0) {
          parts.push(`\nCandidati (${r.candidates.length}):`);
          for (const c of r.candidates.slice(0, 5)) {
            parts.push(`  • ${c.alias} (${c.entity_id.split(':').pop()}) score=${c.score.toFixed(2)} via=${c.source}`);
          }
        }
        if (r.needs_clarification) parts.push('\n⚠ Risultato ambiguo, serve chiarificazione.');
      }
      setVoiceResult(parts.join('\n'));
    } catch (e) {
      setVoiceResult(`Errore: ${(e as Error).message}`);
    } finally {
      setVoiceBusy(false);
    }
  }

  async function quickToggle(e: Entity) {
    setServiceTarget(e);
    setServiceOpen(true);
  }

  async function performService(e: Entity, action: 'turn_on' | 'turn_off' | 'toggle') {
    try {
      const localId = e.id.split(':', 2)[1];
      const domain = localId.split('.', 1)[0];
      await callService({ domain, service: action, entity_id: e.id });
      toast.push({ kind: 'ok', title: `${action} eseguito su ${e.friendly_name}` });
      // Refresh entities to reflect new state.
      try { setEntities(await listEntities()); } catch {/* */}
      setServiceOpen(false);
    } catch (err) {
      toast.push({
        kind: 'alert',
        title: 'Comando fallito',
        body: (err as Error).message,
      });
    }
  }

  // Group entities by domain.
  const grouped = useMemo(() => {
    if (!entities) return null;
    const filtered = domainFilter === 'all'
      ? entities
      : entities.filter(e => e.domain === domainFilter);
    const out: Record<string, Entity[]> = {};
    for (const e of filtered) {
      (out[e.domain] ??= []).push(e);
    }
    return out;
  }, [entities, domainFilter]);

  const allDomains = useMemo(() => {
    if (!entities) return [];
    return Array.from(new Set(entities.map(e => e.domain))).sort();
  }, [entities]);

  return (
    <div className="px-5 md:px-8 max-w-5xl mx-auto pb-8">
      <div className="mb-5">
        <h1 className="font-display text-3xl md:text-4xl text-fg leading-tight">
          Smart Home · Admin
        </h1>
        <p className="text-sm text-fg-soft mt-1">
          Connessione Home Assistant, mappa entità, test del riconoscimento vocale.
        </p>
      </div>

      {/* Connection */}
      <Card variant="raised" className="mb-5">
        <div className="flex items-center justify-between gap-3 mb-4">
          <CardTitle className="!text-lg">Connessione Home Assistant</CardTitle>
          {health && (
            <Badge tone={health.ok ? 'ok' : 'alert'} dot>
              {health.ok ? 'connesso' : 'non raggiungibile'}
            </Badge>
          )}
        </div>

        <label className="inline-flex items-center gap-3 mb-4 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={enabled}
            onChange={e => setEnabled(e.target.checked)}
            className="accent-accent w-5 h-5"
          />
          <span className="text-sm text-fg">Smart Home attivo</span>
        </label>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="URL Home Assistant" hint="Es. http://192.168.1.x:8123">
            <Input
              value={haUrl}
              onChange={e => setHaUrl(e.target.value)}
              placeholder="http://192.168.1.x:8123"
              type="url"
            />
          </Field>
          <Field
            label="Token long-lived"
            hint="Generato in HA: Profilo → Token di accesso"
          >
            <Input
              value={haToken}
              onChange={e => setHaToken(e.target.value)}
              placeholder="•••"
              type="password"
            />
          </Field>
        </div>

        <div className="mt-4 flex justify-end">
          <Button
            variant="primary"
            size="sm"
            loading={savingConfig}
            onClick={() => void saveConfig()}
          >
            Salva e prova
          </Button>
        </div>

        {health && (
          <div className="mt-3 text-xs text-fg-muted">
            {health.detail}
            {health.last_event_age_s !== null && (
              <> · ultimo evento {Math.round(health.last_event_age_s)}s fa</>
            )}
          </div>
        )}
      </Card>

      {/* Voice mapping test */}
      <Card variant="raised" className="mb-5">
        <CardTitle className="!text-lg">Prova mappatura vocale</CardTitle>
        <CardSubtitle className="!mt-1 mb-3">
          Scrivi quello che diresti a voce. Vediamo come Cara lo risolve.
        </CardSubtitle>
        <div className="flex gap-2 items-end">
          <Input
            value={voiceTest}
            onChange={e => setVoiceTest(e.target.value)}
            placeholder='Es. "Accendi la luce della cucina"'
            className="flex-1"
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault();
                void runVoiceTest();
              }
            }}
          />
          <Button
            variant="primary"
            size="md"
            loading={voiceBusy}
            disabled={!voiceTest.trim()}
            onClick={() => void runVoiceTest()}
          >
            Risolvi
          </Button>
        </div>
        {voiceResult !== null && (
          <pre className="mt-3 text-2xs text-fg whitespace-pre-wrap font-mono bg-surface2 rounded-md p-3 leading-relaxed">
            {voiceResult}
          </pre>
        )}
      </Card>

      {/* Entities */}
      {enabled && (
        <Card variant="flat" padded={false} className="mb-5">
          <div className="flex items-center justify-between gap-3 px-5 pt-5 pb-3">
            <CardTitle className="!text-lg">Entità</CardTitle>
            <Badge tone="muted" size="sm">
              {entities ? `${entities.length} totali` : '…'}
            </Badge>
          </div>

          {entities && entities.length > 0 && (
            <div className="px-5 pb-3 flex flex-wrap gap-1.5">
              {(['all', ...allDomains] as const).map(d => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDomainFilter(d)}
                  className={cn(
                    'text-xs rounded-pill px-3 py-1 transition-all',
                    domainFilter === d
                      ? 'bg-accent text-ivory shadow-warm'
                      : 'bg-surface1 hover:bg-surface2 text-fg-soft',
                  )}
                >
                  {d === 'all' ? 'tutte' : deriveDomainGroup(d)}
                </button>
              ))}
            </div>
          )}

          {entities === null && (
            <div className="px-5 pb-5 text-sm text-fg-muted">caricamento…</div>
          )}
          {entities !== null && entities.length === 0 && (
            <div className="px-5 pb-5 text-sm text-fg-muted">
              Nessuna entità. Verifica URL e token.
            </div>
          )}
          {grouped && Object.keys(grouped).length > 0 && (
            <div className="divide-y divide-fg/8">
              {Object.entries(grouped).map(([dom, ents]) => (
                <div key={dom} className="px-5 py-3">
                  <h3 className="text-xs uppercase tracking-wider text-fg-muted mb-2">
                    {deriveDomainGroup(dom)} ({ents.length})
                  </h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
                    {ents.map(e => (
                      <button
                        key={e.id}
                        type="button"
                        onClick={() => void quickToggle(e)}
                        className={cn(
                          'flex items-center justify-between gap-2 rounded-md p-2.5 text-left',
                          'bg-surface1 hover:bg-surface2 ring-1 ring-fg/8 transition-all',
                        )}
                      >
                        <div className="min-w-0">
                          <div className="text-xs font-medium text-fg truncate">
                            {e.friendly_name}
                          </div>
                          <div className="text-2xs text-fg-muted truncate">
                            {e.area ? `${e.area} · ` : ''}{e.id.split(':').pop()}
                          </div>
                        </div>
                        <Badge
                          tone={
                            e.state === 'on' || e.state === 'open' ? 'ok'
                              : e.state === 'off' || e.state === 'closed' ? 'muted'
                              : 'accent'
                          }
                          size="sm"
                        >
                          {e.state ?? '—'}
                        </Badge>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* Quick service sheet */}
      <BottomSheet
        open={serviceOpen}
        onClose={() => setServiceOpen(false)}
        title={serviceTarget?.friendly_name}
        subtitle={serviceTarget?.id.split(':').pop()}
      >
        {serviceTarget && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <Button
              variant="ok"
              size="md"
              onClick={() => void performService(serviceTarget, 'turn_on')}
            >
              Accendi
            </Button>
            <Button
              variant="surface"
              size="md"
              onClick={() => void performService(serviceTarget, 'toggle')}
            >
              Inverti
            </Button>
            <Button
              variant="alert"
              size="md"
              onClick={() => void performService(serviceTarget, 'turn_off')}
            >
              Spegni
            </Button>
          </div>
        )}
      </BottomSheet>
    </div>
  );
}
