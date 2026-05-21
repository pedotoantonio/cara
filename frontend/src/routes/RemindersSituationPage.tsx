// RemindersSituationPage — galleria delle "situazioni guidate" per
// una categoria. Tap su una situazione → form di creazione.

import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import {
  CATEGORY_META,
  type ReminderCategory,
  type ReminderTemplate,
  listTemplates,
} from '../api/reminders';
import { Card } from '../design';

const ALL: ReminderCategory[] = ['family', 'health', 'documents', 'events'];

export function RemindersSituationPage() {
  const { category } = useParams<{ category: string }>();
  const navigate = useNavigate();
  const cat = (ALL as string[]).includes(category ?? '') ? (category as ReminderCategory) : null;

  const [templates, setTemplates] = useState<ReminderTemplate[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!cat) return;
    let cancelled = false;
    listTemplates(cat)
      .then((r) => !cancelled && setTemplates(r))
      .catch(() => { /* empty */ })
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [cat]);

  if (!cat) {
    return (
      <main className="min-h-dvh bg-bg text-fg p-6">
        <p>Categoria sconosciuta.</p>
      </main>
    );
  }

  const meta = CATEGORY_META[cat];

  return (
    <main className="min-h-dvh bg-bg text-fg px-4 pt-6 pb-24 max-w-2xl mx-auto">
      <button
        onClick={() => navigate('/reminders')}
        className="text-sm text-fg-muted mb-4 hover:text-fg"
      >
        ← Indietro
      </button>
      <header className="mb-6">
        <div className="text-4xl mb-2">{meta.emoji}</div>
        <h1 className="text-2xl font-bold">{meta.label}</h1>
        <p className="text-fg-muted text-sm mt-1">
          Cosa vuoi ricordare?
        </p>
      </header>

      {loading ? (
        <p className="text-fg-muted">Caricamento…</p>
      ) : (
        <ul className="space-y-2">
          {templates.map((t) => (
            <li key={t.slug}>
              <button
                className="w-full text-left active:scale-[0.98] transition-transform"
                onClick={() => navigate(`/reminders/new/${t.slug}`)}
              >
                <Card className="p-4 flex items-center gap-4 hover:shadow-md transition-shadow">
                  <span className="text-3xl shrink-0">{t.icon}</span>
                  <span className="font-medium">{t.title_it}</span>
                  <span className="ml-auto text-fg-muted">›</span>
                </Card>
              </button>
            </li>
          ))}
          {templates.length === 0 && (
            <li className="text-fg-muted text-sm">
              Nessuna situazione configurata per questa categoria.
            </li>
          )}
        </ul>
      )}
    </main>
  );
}

export default RemindersSituationPage;
