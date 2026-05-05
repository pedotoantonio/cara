// /me/integrazioni — gestione connessioni Google Calendar + Gmail.
//
// L'utente vede lo stato di ogni connessione, può aggiungerne, configurarle
// (quale calendario, push on/off, cloud fallback per email) e disconnettere.

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import {
  GoogleCalendar,
  Integration,
  disconnectIntegration,
  getOAuthStatus,
  listGoogleCalendars,
  listIntegrations,
  setIntegrationConfig,
  startGoogleAuth,
} from '../api/integrations';
import {
  Badge,
  BottomSheet,
  Button,
  Card,
  CardSubtitle,
  CardTitle,
  Field,
  Icon,
  cn,
  useToast,
} from '../design';


function fmtDate(iso: string | null): string {
  if (!iso) return 'mai';
  return new Date(iso).toLocaleString('it-IT', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  });
}


export function IntegrationsPage() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [oauthAvailable, setOauthAvailable] = useState<boolean | null>(null);
  const [integrations, setIntegrations] = useState<Integration[] | null>(null);
  const [busy, setBusy] = useState(false);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [calendarsList, setCalendarsList] = useState<GoogleCalendar[] | null>(null);
  const [pickerTarget, setPickerTarget] = useState<Integration | null>(null);
  const [pickerSelected, setPickerSelected] = useState('');
  const [pickerPushEnabled, setPickerPushEnabled] = useState(false);

  // Read OAuth callback result from URL.
  useEffect(() => {
    const status = params.get('google');
    if (status === 'connected') {
      const scope = params.get('scope') || '';
      toast.push({
        kind: 'celebrate',
        title: 'Connesso a Google',
        body: scope ? `Scope: ${scope}` : undefined,
      });
      // Strip the query so a refresh doesn't re-toast.
      params.delete('google');
      params.delete('scope');
      setParams(params, { replace: true });
    } else if (status === 'error') {
      toast.push({
        kind: 'alert',
        title: 'Connessione fallita',
        body: params.get('detail') || 'Riprova fra un momento.',
      });
      params.delete('google');
      params.delete('detail');
      setParams(params, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refresh() {
    try {
      setIntegrations(await listIntegrations());
    } catch {
      toast.push({ kind: 'alert', title: 'Connessioni non disponibili' });
    }
  }

  useEffect(() => {
    void (async () => {
      try {
        setOauthAvailable((await getOAuthStatus()).available);
      } catch {
        setOauthAvailable(false);
      }
    })();
    void refresh();
  }, []);

  async function connect(scope: 'calendar:rw' | 'gmail:ro') {
    setBusy(true);
    try {
      const url = await startGoogleAuth(scope);
      window.location.href = url;
    } catch (e) {
      setBusy(false);
      toast.push({
        kind: 'alert', title: 'Avvio OAuth fallito',
        body: (e as Error).message,
      });
    }
  }

  async function openConfig(it: Integration) {
    setPickerTarget(it);
    setPickerSelected(String(it.config?.calendar_id ?? 'primary'));
    setPickerPushEnabled(Boolean(it.config?.push_enabled));
    setCalendarsList(null);
    setPickerOpen(true);
    if (it.scope_set === 'calendar:rw') {
      try {
        setCalendarsList(await listGoogleCalendars());
      } catch {
        setCalendarsList([]);
        toast.push({ kind: 'alert', title: 'Impossibile leggere i calendari' });
      }
    }
  }

  async function saveConfig() {
    if (!pickerTarget) return;
    try {
      await setIntegrationConfig(pickerTarget.id, {
        calendar_id: pickerSelected || undefined,
        push_enabled: pickerPushEnabled,
      });
      toast.push({ kind: 'ok', title: 'Configurazione salvata' });
      setPickerOpen(false);
      await refresh();
    } catch {
      toast.push({ kind: 'alert', title: 'Salvataggio fallito' });
    }
  }

  async function disconnect(it: Integration) {
    if (!confirm(`Disconnettere ${it.account_email}?`)) return;
    try {
      await disconnectIntegration(it.id);
      toast.push({ kind: 'ok', title: 'Disconnesso' });
      await refresh();
    } catch {
      toast.push({ kind: 'alert', title: 'Disconnessione fallita' });
    }
  }

  const calendarConn = useMemo(
    () => integrations?.find(i => i.scope_set === 'calendar:rw' && !i.revoked),
    [integrations],
  );
  const gmailConn = useMemo(
    () => integrations?.find(i => i.scope_set === 'gmail:ro' && !i.revoked),
    [integrations],
  );

  return (
    <div className="px-5 md:px-8 max-w-3xl mx-auto pb-8">
      <div className="mb-5">
        <h1 className="font-display text-3xl md:text-4xl text-fg leading-tight">
          Integrazioni
        </h1>
        <p className="text-sm text-fg-soft mt-1">
          Connetti Google Calendar e Gmail. Cara legge gli eventi e propone
          impegni dalle email — niente in cloud senza il tuo permesso.
        </p>
      </div>

      {oauthAvailable === false && (
        <Card variant="outline" tint="alert" className="mb-5">
          <p className="text-sm text-fg leading-snug">
            Le integrazioni Google non sono ancora configurate dall'admin.
            Aggiungi <code>GOOGLE_OAUTH_CLIENT_ID</code> e
            <code>_SECRET</code> nel <code>.env</code>, poi riavvia il backend.
          </p>
        </Card>
      )}

      {/* Calendar */}
      <Card variant="raised" className="mb-4">
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="min-w-0">
            <CardTitle className="!text-lg">Google Calendar</CardTitle>
            <CardSubtitle>
              Cara legge gli eventi nei prossimi 7 giorni e li mette nei tuoi task.
            </CardSubtitle>
          </div>
          <Icon name="calendar" size={22} className="text-accent shrink-0" />
        </div>

        {calendarConn ? (
          <div className="mt-3 space-y-2">
            <div className="flex items-center gap-2 text-sm text-fg">
              <Badge tone="ok" dot size="sm">connesso</Badge>
              <span className="truncate">{calendarConn.account_email}</span>
            </div>
            <div className="text-xs text-fg-muted">
              Calendario: {String(calendarConn.config?.calendar_id || 'primary')}
              {calendarConn.config?.push_enabled
                ? ' · push attivo (Cara → Google)'
                : ' · solo lettura'}
            </div>
            <div className="text-xs text-fg-muted">
              Ultima sync: {fmtDate(calendarConn.last_synced_at)}
            </div>
            <div className="flex gap-2 mt-3">
              <Button
                variant="surface" size="sm" iconLeft="settings"
                onClick={() => void openConfig(calendarConn)}
              >
                Configura
              </Button>
              <Button
                variant="ghost" size="sm" iconLeft="close"
                onClick={() => void disconnect(calendarConn)}
                className="text-alert"
              >
                Disconnetti
              </Button>
            </div>
          </div>
        ) : (
          <Button
            variant="primary" size="sm" iconLeft="plus"
            disabled={!oauthAvailable || busy}
            onClick={() => void connect('calendar:rw')}
          >
            Connetti Google Calendar
          </Button>
        )}
      </Card>

      {/* Gmail */}
      <Card variant="raised" className="mb-4">
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="min-w-0">
            <CardTitle className="!text-lg">Gmail</CardTitle>
            <CardSubtitle>
              Cara cerca impegni nelle email recenti e ti propone task.
              Non risponde mai per te.
            </CardSubtitle>
          </div>
          <Icon name="news" size={22} className="text-accent shrink-0" />
        </div>

        {gmailConn ? (
          <div className="mt-3 space-y-2">
            <div className="flex items-center gap-2 text-sm text-fg">
              <Badge tone="ok" dot size="sm">connesso</Badge>
              <span className="truncate">{gmailConn.account_email}</span>
            </div>
            <div className="text-xs text-fg-muted">
              {gmailConn.config?.cloud_fallback_enabled
                ? 'Cloud fallback attivo per email difficili'
                : 'Solo elaborazione locale'}
            </div>
            <div className="text-xs text-fg-muted">
              Ultima scansione: {fmtDate(gmailConn.last_synced_at)}
            </div>
            <div className="flex gap-2 mt-3">
              <Button
                variant="ghost" size="sm" iconLeft="close"
                onClick={() => void disconnect(gmailConn)}
                className="text-alert"
              >
                Disconnetti
              </Button>
            </div>
          </div>
        ) : (
          <Button
            variant="primary" size="sm" iconLeft="plus"
            disabled={!oauthAvailable || busy}
            onClick={() => void connect('gmail:ro')}
          >
            Connetti Gmail
          </Button>
        )}
      </Card>

      {/* Privacy note */}
      <Card variant="outline" className="text-xs text-fg-soft leading-relaxed">
        <p className="mb-2 font-medium text-fg">Cosa esce di casa</p>
        <ul className="space-y-1.5 list-disc pl-4">
          <li>I token Google sono cifrati AES-256 nel database.</li>
          <li>Calendar: Cara legge eventi e (opzionalmente) ne crea di nuovi.</li>
          <li>Gmail: Cara legge solo i messaggi non letti delle ultime 24h, salta promo + social, e non scrive mai email.</li>
          <li>Nessun corpo email viene salvato. Solo un'anteprima di 200 caratteri per ogni proposta.</li>
          <li>Disconnect = revoca server-side su Google + cancellazione token.</li>
        </ul>
      </Card>

      {/* Calendar picker sheet */}
      <BottomSheet
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        title="Configura calendario"
        subtitle={pickerTarget?.account_email}
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setPickerOpen(false)}>
              Annulla
            </Button>
            <Button variant="primary" size="sm" onClick={() => void saveConfig()}>
              Salva
            </Button>
          </div>
        }
      >
        {pickerTarget?.scope_set === 'calendar:rw' && (
          <>
            <Field label="Calendario da sincronizzare" hint="Cara importa eventi solo da quello selezionato.">
              {calendarsList === null ? (
                <div className="h-11 rounded-lg bg-surface1 animate-breathe" />
              ) : (
                <select
                  value={pickerSelected}
                  onChange={e => setPickerSelected(e.target.value)}
                  className="w-full h-11 rounded-lg bg-surface1 ring-1 ring-fg/8 px-3 text-fg focus:outline-none focus:ring-2 focus:ring-accent"
                >
                  {calendarsList.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.summary}{c.primary ? ' (primario)' : ''}
                    </option>
                  ))}
                </select>
              )}
            </Field>

            <Field
              label="Pubblica anche su Google"
              hint="Se attivo, le task con scadenza che crei in Cara appaiono come eventi sul calendario selezionato."
              className="mt-4"
            >
              <label className="inline-flex items-center gap-3 cursor-pointer select-none">
                <button
                  type="button"
                  onClick={() => setPickerPushEnabled(!pickerPushEnabled)}
                  className={cn(
                    'w-12 h-7 rounded-pill p-0.5 transition-all',
                    pickerPushEnabled ? 'bg-accent' : 'bg-surface2',
                  )}
                >
                  <span className={cn(
                    'block h-6 w-6 rounded-pill bg-ivory shadow-soft transition-all',
                    pickerPushEnabled ? 'translate-x-5' : 'translate-x-0',
                  )} />
                </button>
                <span className="text-sm text-fg">
                  {pickerPushEnabled ? 'Push attivo' : 'Solo lettura'}
                </span>
              </label>
            </Field>
          </>
        )}
      </BottomSheet>
    </div>
  );
}
