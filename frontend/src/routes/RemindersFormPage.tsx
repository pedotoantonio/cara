// RemindersFormPage — form di creazione guidata per UN template.
//
// Renderizza dinamicamente i `fields` del template. Ogni campo ha un
// tipo (`text`, `date`, `datetime`, `family_picker`, …). I default di
// lead-time + recurrence vengono direttamente dal template — NON
// chiediamo niente di tecnico all'utente.

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { listUsers } from '../api/users';
import {
  type ReminderTemplate,
  type TemplateField,
  createReminder,
  leadTimeLabel,
  listTemplates,
} from '../api/reminders';
import { Button, Card, Field, Input, useToast } from '../design';

interface FamilyOption {
  id: number;
  label: string;
}

export function RemindersFormPage() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const toast = useToast();

  const [template, setTemplate] = useState<ReminderTemplate | null>(null);
  const [family, setFamily] = useState<FamilyOption[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    listTemplates()
      .then((all) => {
        if (cancelled) return;
        const t = all.find((x) => x.slug === slug) ?? null;
        setTemplate(t);
      })
      .catch(() => { /* ignore */ });
    // Family picker depends on /admin/users — if the endpoint is not
    // reachable (non-admin), we fall back to "yourself" implicit.
    listUsers()
      .then((users) => {
        if (cancelled) return;
        setFamily(users.map((u) => ({
          id: u.id,
          label: u.full_name || u.email,
        })));
      })
      .catch(() => { /* silent */ });
    return () => { cancelled = true; };
  }, [slug]);

  const hasDateField = useMemo(
    () => template?.fields.some((f) => f.type === 'date' || f.type === 'datetime'),
    [template],
  );

  if (!template) {
    return <main className="min-h-dvh bg-bg p-6 text-fg-muted">Caricamento…</main>;
  }

  function update(key: string, v: string) {
    setValues((s) => ({ ...s, [key]: v }));
    setError(null);
  }

  async function submit() {
    if (!template) return;

    // Validate required
    const missing = template.fields.find(
      (f) => f.required && !(values[f.key] ?? '').trim(),
    );
    if (missing) {
      setError(`Manca: ${missing.label}`);
      return;
    }

    // Resolve due_at — every reminder needs one. Look for `when` field
    // first, then any field of type date/datetime.
    let dueRaw = values.when ?? '';
    if (!dueRaw) {
      const dateField = template.fields.find(
        (f) => f.type === 'date' || f.type === 'datetime',
      );
      if (dateField) dueRaw = values[dateField.key] ?? '';
    }
    if (!dueRaw) {
      setError('Manca la data');
      return;
    }
    // Local datetime → ISO with offset. "date" inputs (no time) default
    // to 09:00 local — sensibile per scadenze documenti.
    let due = dueRaw;
    if (!due.includes('T')) due = `${due}T09:00`;
    const dueIso = new Date(due).toISOString();

    // Subject — `who` field if present.
    const who = values.who;
    const family_id = who ? Number(who) : undefined;
    const subjectLabel = family.find((f) => String(f.id) === who)?.label;

    // Extras: every non-special key gets shoved into extras for the
    // backend to use in title composition.
    const extras: Record<string, string> = {};
    for (const f of template.fields) {
      if (f.key === 'who' || f.key === 'when') continue;
      const v = values[f.key];
      if (v) extras[f.key] = v;
    }
    if (subjectLabel) extras.subject_label = subjectLabel;

    setSubmitting(true);
    try {
      await createReminder({
        template_slug: template.slug,
        due_at: dueIso,
        family_id: family_id ?? undefined,
        notes: values.notes || undefined,
        extras,
      });
      toast.push({ kind: 'ok', title: 'Te lo ricorderò 🌿' });
      navigate('/reminders');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Errore');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-dvh bg-bg text-fg px-4 pt-6 pb-24 max-w-xl mx-auto">
      <button
        onClick={() => navigate(-1)}
        className="text-sm text-fg-muted mb-4 hover:text-fg"
      >
        ← Indietro
      </button>
      <header className="mb-6">
        <div className="text-4xl mb-2">{template.icon}</div>
        <h1 className="text-2xl font-bold">{template.title_it}</h1>
      </header>

      <Card className="p-5 space-y-4">
        {template.fields.map((f) => (
          <RenderField
            key={f.key}
            field={f}
            value={values[f.key] ?? ''}
            family={family}
            onChange={(v) => update(f.key, v)}
          />
        ))}

        {template.default_lead_times.length > 0 && (
          <div className="text-sm text-fg-muted pt-2 border-t border-fg/10">
            Ti avviserò: {template.default_lead_times.map(leadTimeLabel).join(' · ')}
            {template.default_recurrence === 'yearly' && ', ogni anno'}
            {template.default_recurrence === 'monthly' && ', ogni mese'}
            {template.default_recurrence === 'weekly' && ', ogni settimana'}
          </div>
        )}

        {error && <div className="text-sm text-rose-600 dark:text-rose-400">{error}</div>}

        <Button
          className="w-full"
          variant="primary"
          onClick={submit}
          disabled={submitting || !hasDateField}
        >
          {submitting ? 'Salvataggio…' : 'Salva il ricordo'}
        </Button>
      </Card>
    </main>
  );
}

function RenderField({
  field, value, onChange, family,
}: {
  field: TemplateField;
  value: string;
  onChange: (v: string) => void;
  family: FamilyOption[];
}) {
  if (field.type === 'family_picker') {
    return (
      <Field label={field.label}>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-2xl bg-bg-soft border border-fg/15 px-4 py-3"
        >
          <option value="">— Seleziona —</option>
          {family.map((f) => (
            <option key={f.id} value={String(f.id)}>{f.label}</option>
          ))}
        </select>
      </Field>
    );
  }
  if (field.type === 'date') {
    return (
      <Field label={field.label}>
        <Input
          type="date"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </Field>
    );
  }
  if (field.type === 'datetime') {
    return (
      <Field label={field.label}>
        <Input
          type="datetime-local"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </Field>
    );
  }
  if (field.type === 'select' && field.options) {
    return (
      <Field label={field.label}>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-2xl bg-bg-soft border border-fg/15 px-4 py-3"
        >
          <option value="">— Seleziona —</option>
          {field.options.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </Field>
    );
  }
  return (
    <Field label={field.label}>
      <Input
        type="text"
        value={value}
        placeholder={field.placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  );
}

export default RemindersFormPage;
