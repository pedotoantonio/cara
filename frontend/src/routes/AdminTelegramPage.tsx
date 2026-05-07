/**
 * Admin "Telegram" page — gestione chat ↔ utente CARA.
 *
 * Quando un familiare apre @cara_pedoto_bot e fa /start, il bot
 * lo respinge se il suo chat_id non è in nessun mapping. L'admin
 * deve aggiungerlo qui (è anche il modo per ottenere l'id, vedi
 * istruzioni in fondo).
 */

import { useEffect, useState } from 'react';

import {
  TelegramMapping,
  createTelegramMapping,
  deleteTelegramMapping,
  listTelegramMappings,
  sendTestTelegram,
  updateTelegramMapping,
} from '../api/adminTelegram';
import { Card, Icon } from '../design';

function relTime(iso: string | null): string {
  if (!iso) return 'mai';
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms) || ms < 0) return 'mai';
  const min = Math.round(ms / 60_000);
  if (min < 1) return 'adesso';
  if (min < 60) return `${min} min fa`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h}h fa`;
  return `${Math.round(h / 24)}g fa`;
}

export function AdminTelegramPage() {
  const [rows, setRows] = useState<TelegramMapping[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showAdd, setShowAdd] = useState(false);

  async function refresh() {
    setLoading(true); setError(null);
    try {
      setRows(await listTelegramMappings());
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }
  useEffect(() => { void refresh(); }, []);

  return (
    <main className="px-4 md:px-8 py-6 max-w-3xl mx-auto space-y-6 pb-24">
      <header className="flex items-center justify-between">
        <h1 className="font-display text-2xl text-fg">Telegram</h1>
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="inline-flex items-center gap-2 rounded-pill bg-accent text-bg px-4 py-2 text-sm font-medium"
        >
          <Icon name="plus" size={16} /> Aggiungi chat
        </button>
      </header>

      {error && (
        <Card variant="outline" tint="alert">
          <p className="text-sm text-alert">⚠ {error}</p>
        </Card>
      )}

      {loading && rows === null && (
        <p className="text-sm text-fg-muted">Carico…</p>
      )}

      {rows && rows.length === 0 && (
        <Card>
          <p className="text-sm text-fg-muted">
            Nessuna chat configurata. Tocca "Aggiungi chat" per mappare un familiare.
          </p>
        </Card>
      )}

      {rows && rows.length > 0 && (
        <ul className="space-y-3">
          {rows.map((m) => (
            <MappingCard key={m.chat_id} mapping={m} onChange={refresh} />
          ))}
        </ul>
      )}

      <Card variant="outline">
        <h2 className="font-medium mb-2">Come ottenere il chat_id</h2>
        <ol className="text-sm text-fg-soft list-decimal list-inside space-y-1">
          <li>Il familiare apre @cara_pedoto_bot e tocca <b>/start</b>.</li>
          <li>Il bot risponde "Non sei autorizzato" — è normale al primo passaggio.</li>
          <li>L'admin (tu) apre <a className="text-accent underline" href="https://t.me/userinfobot" target="_blank" rel="noopener">@userinfobot</a>{' '}
            e gli chiede di leggere il chat_id del familiare (oppure si guarda <code>getUpdates</code>).</li>
          <li>Inserisci qui chat_id + email CARA del familiare.</li>
        </ol>
      </Card>

      {showAdd && (
        <AddMappingModal
          onClose={() => setShowAdd(false)}
          onCreated={() => { setShowAdd(false); void refresh(); }}
        />
      )}
    </main>
  );
}

function MappingCard({
  mapping, onChange,
}: { mapping: TelegramMapping; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const isEnv = mapping.source === 'env';

  async function toggle(field: 'notifications_enabled' | 'voice_enabled') {
    setBusy(true); setErr(null);
    try {
      await updateTelegramMapping(mapping.chat_id, {
        [field]: !mapping[field],
      } as Record<string, unknown>);
      onChange();
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!confirm(`Rimuovere il mapping per ${mapping.user_email}?`)) return;
    setBusy(true); setErr(null);
    try { await deleteTelegramMapping(mapping.chat_id); onChange(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }
  async function test() {
    setBusy(true); setErr(null);
    try {
      await sendTestTelegram(mapping.chat_id);
      alert('Messaggio di test inviato. Controlla il bot.');
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="font-medium">{mapping.user_email}</p>
            {isEnv && (
              <span className="text-2xs bg-surface2 rounded-pill px-2 py-0.5 text-fg-muted">
                env
              </span>
            )}
            {mapping.label && (
              <span className="text-2xs text-fg-soft">— {mapping.label}</span>
            )}
          </div>
          <p className="text-2xs text-fg-muted mt-0.5">
            chat_id <code>{mapping.chat_id}</code> · ultima attività {relTime(mapping.last_active_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <label className="inline-flex items-center gap-1.5 text-2xs cursor-pointer">
            <input
              type="checkbox"
              checked={mapping.notifications_enabled}
              disabled={busy || isEnv}
              onChange={() => toggle('notifications_enabled')}
            />
            notifiche
          </label>
          <label className="inline-flex items-center gap-1.5 text-2xs cursor-pointer">
            <input
              type="checkbox"
              checked={mapping.voice_enabled}
              disabled={busy || isEnv}
              onChange={() => toggle('voice_enabled')}
            />
            voce
          </label>
        </div>
      </div>

      {err && <p className="text-2xs text-alert mt-2">⚠ {err}</p>}

      <div className="flex gap-2 mt-3 flex-wrap">
        <button
          type="button"
          onClick={test}
          disabled={busy}
          className="text-xs rounded-pill bg-surface2 px-3 py-1.5"
        >
          🧪 Test
        </button>
        {!isEnv && (
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            className="text-xs text-alert px-3 py-1.5 ml-auto"
          >
            Elimina
          </button>
        )}
      </div>
    </Card>
  );
}

function AddMappingModal({
  onClose, onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [chatId, setChatId] = useState('');
  const [email, setEmail] = useState('');
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    const cid = parseInt(chatId.trim(), 10);
    if (!Number.isFinite(cid)) { setErr('chat_id deve essere un numero'); return; }
    if (!email.trim()) { setErr('email CARA obbligatoria'); return; }
    setBusy(true); setErr(null);
    try {
      await createTelegramMapping({
        chat_id: cid,
        user_email: email.trim(),
        label: label.trim() || null,
      });
      onCreated();
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-bg rounded-lg max-w-md w-full p-5 space-y-3" onClick={(e) => e.stopPropagation()}>
        <h2 className="font-display text-lg">Nuovo mapping</h2>

        <div>
          <label className="block text-xs text-fg-muted mb-1">Chat ID Telegram</label>
          <input
            autoFocus
            value={chatId}
            onChange={(e) => setChatId(e.target.value)}
            placeholder="892776592"
            inputMode="numeric"
            className="w-full bg-surface2 rounded-md px-3 py-2"
          />
        </div>

        <div>
          <label className="block text-xs text-fg-muted mb-1">Email CARA</label>
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="sara@cara.local"
            className="w-full bg-surface2 rounded-md px-3 py-2"
          />
        </div>

        <div>
          <label className="block text-xs text-fg-muted mb-1">Etichetta (opzionale)</label>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Mamma di Matteo"
            className="w-full bg-surface2 rounded-md px-3 py-2"
          />
        </div>

        {err && <p className="text-xs text-alert">⚠ {err}</p>}

        <div className="flex gap-2 justify-end pt-2">
          <button type="button" onClick={onClose} className="text-sm text-fg-muted px-3 py-1.5">
            Annulla
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy || !chatId || !email}
            className="text-sm rounded-pill bg-accent text-bg px-4 py-1.5 disabled:opacity-40"
          >
            {busy ? 'Salvo…' : 'Crea'}
          </button>
        </div>
      </div>
    </div>
  );
}
