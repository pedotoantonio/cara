/**
 * Admin "Famiglia" page — list users + inline edit dialog.
 *
 * Email and password are NOT editable here by design (they need
 * dedicated flows). Everything else (name, role, birth date, wall
 * presentation, activation) can be edited.
 */

import { useEffect, useState } from 'react';

import { listUsers, updateUser, type User, type UserPatch } from '../api/users';
import { Button, Card, CardTitle, Field, Icon, Input, useToast } from '../design';

const ROLE_OPTIONS = ['parent', 'child', 'guest'] as const;
const EMOJI_OPTIONS = ['👤', '👨', '👩', '👦', '👧', '👴', '👵', '🧑'];
const COLOR_OPTIONS = [
  '#ef4444', '#f97316', '#eab308', '#84cc16', '#10b981',
  '#06b6d4', '#3b82f6', '#8b5cf6', '#ec4899', '#64748b',
];


function EditDialog({
  user, onClose, onSaved,
}: {
  user: User;
  onClose: () => void;
  onSaved: (u: User) => void;
}) {
  const [form, setForm] = useState<UserPatch>({
    full_name: user.full_name ?? '',
    role: user.role,
    birth_date: user.birth_date ?? '',
    is_active: user.is_active,
    wall_visible: user.wall_visible,
    wall_color: user.wall_color ?? '#3b82f6',
    wall_emoji: user.wall_emoji ?? '👤',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  async function save() {
    setSaving(true);
    setError(null);
    try {
      // Convert empty birth_date string to null so it actually clears.
      const payload: UserPatch = { ...form };
      if (payload.birth_date === '') payload.birth_date = null;
      const updated = await updateUser(user.id, payload);
      onSaved(updated);
      toast.push({ kind: 'ok', title: `${updated.full_name ?? updated.email} aggiornato` });
      onClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <Card className="w-full max-w-md p-6 space-y-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <CardTitle>Modifica {user.email}</CardTitle>
          <button onClick={onClose} className="text-fg-muted hover:text-fg" aria-label="Chiudi">
            <Icon name="close" size={20} />
          </button>
        </div>

        <Field label="Nome completo">
          <Input
            value={form.full_name ?? ''}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            placeholder="Es. Sara Pedoto"
          />
        </Field>

        <Field label="Ruolo">
          <select
            className="w-full h-11 bg-surface1 text-fg rounded-lg border-0 ring-1 ring-fg/8 px-3"
            value={form.role ?? 'parent'}
            onChange={(e) => setForm({ ...form, role: e.target.value })}
          >
            {ROLE_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </Field>

        <Field label="Data di nascita">
          <Input
            type="date"
            value={form.birth_date ?? ''}
            onChange={(e) => setForm({ ...form, birth_date: e.target.value })}
          />
        </Field>

        <Field label="Emoji wall">
          <div className="flex gap-2 flex-wrap">
            {EMOJI_OPTIONS.map((emo) => (
              <button
                key={emo}
                type="button"
                onClick={() => setForm({ ...form, wall_emoji: emo })}
                className={`w-9 h-9 rounded-lg text-lg ${form.wall_emoji === emo ? 'ring-2 ring-accent' : 'ring-1 ring-fg/10'}`}
              >{emo}</button>
            ))}
          </div>
        </Field>

        <Field label="Colore wall">
          <div className="flex gap-2 flex-wrap">
            {COLOR_OPTIONS.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setForm({ ...form, wall_color: c })}
                aria-label={c}
                style={{ background: c }}
                className={`w-9 h-9 rounded-lg ${form.wall_color === c ? 'ring-2 ring-fg/40' : ''}`}
              />
            ))}
          </div>
        </Field>

        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.is_active ?? true}
              onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
            />
            Attivo
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.wall_visible ?? true}
              onChange={(e) => setForm({ ...form, wall_visible: e.target.checked })}
            />
            Visibile sul wall
          </label>
        </div>

        {error && (
          <div className="text-sm text-red-500 bg-red-500/10 rounded-lg p-3">{error}</div>
        )}

        <div className="flex gap-2 justify-end pt-2">
          <Button variant="ghost" onClick={onClose} disabled={saving}>Annulla</Button>
          <Button onClick={save} disabled={saving}>{saving ? 'Salvataggio…' : 'Salva'}</Button>
        </div>
      </Card>
    </div>
  );
}


export function AdminUsersPage() {
  const [users, setUsers] = useState<User[] | null>(null);
  const [editing, setEditing] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const data = await listUsers();
      setUsers(data);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => { void refresh(); }, []);

  return (
    <div className="space-y-4 p-4 max-w-4xl mx-auto">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Famiglia</h1>
        <p className="text-sm text-fg-muted">
          Email e password non modificabili da qui — usa il flusso login/setup.
        </p>
      </div>

      {error && (
        <Card className="p-4 text-red-500 bg-red-500/10">{error}</Card>
      )}

      {users === null ? (
        <Card className="p-4 text-fg-muted">Caricamento…</Card>
      ) : (
        <div className="space-y-2">
          {users.map((u) => (
            <Card key={u.id} className="p-4 flex items-center gap-4">
              <div
                className="w-12 h-12 rounded-full flex items-center justify-center text-xl"
                style={{ background: u.wall_color ?? '#64748b' }}
              >{u.wall_emoji ?? '👤'}</div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium">{u.full_name ?? '(senza nome)'}</span>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-fg/10">{u.role}</span>
                  {u.is_admin && <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-600">admin</span>}
                  {!u.is_active && <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/20 text-red-500">disattivato</span>}
                </div>
                <div className="text-sm text-fg-muted truncate">{u.email}</div>
                {u.birth_date && (
                  <div className="text-xs text-fg-muted">Nato/a: {u.birth_date}</div>
                )}
              </div>
              <Button variant="ghost" onClick={() => setEditing(u)}>
                <Icon name="settings" size={16} /> Modifica
              </Button>
            </Card>
          ))}
        </div>
      )}

      {editing && (
        <EditDialog
          user={editing}
          onClose={() => setEditing(null)}
          onSaved={(u) => {
            setUsers((prev) => prev?.map((x) => x.id === u.id ? u : x) ?? null);
          }}
        />
      )}
    </div>
  );
}
