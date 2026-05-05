// /admin/skills — Skill Factory admin UI: list/edit/approve/reject/delete +
// JSON editor with live primitive catalog reference.
import { useEffect, useMemo, useState } from 'react';

import {
  approveSkill,
  deleteSkill,
  listPrimitives,
  listSkills,
  patchSkill,
  rejectSkill,
  type PrimitiveSpec,
  type Skill,
} from '../api/adminSkills';

type Tab = 'pending' | 'active' | 'disabled';

export function AdminSkillsPage() {
  const [tab, setTab] = useState<Tab>('pending');
  const [skills, setSkills] = useState<Skill[]>([]);
  const [primitives, setPrimitives] = useState<PrimitiveSpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<Skill | null>(null);

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      const [sk, pr] = await Promise.all([
        listSkills(tab),
        primitives.length === 0 ? listPrimitives() : Promise.resolve(primitives),
      ]);
      setSkills(sk);
      if (primitives.length === 0) setPrimitives(pr);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const counts = useMemo(() => {
    return { current: skills.length };
  }, [skills]);

  return (
    <main className="flex-1 overflow-y-auto bg-slate-900 text-slate-100">
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        <header className="flex items-baseline justify-between">
          <div>
            <h1 className="text-xl font-medium">Skill Factory</h1>
            <p className="text-xs text-slate-500 mt-0.5">
              Skill JSON che la chat può usare come tool deterministici. Approva
              per attivare; modifica il piano per aggiustare comportamento.
            </p>
          </div>
          <button
            type="button"
            onClick={refresh}
            className="text-xs text-emerald-300 hover:text-emerald-200 underline"
          >
            Aggiorna
          </button>
        </header>

        {/* Tabs */}
        <nav className="flex gap-2 text-xs border-b border-slate-800 pb-1">
          {(['pending', 'active', 'disabled'] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded-t-lg ${
                tab === t
                  ? 'bg-slate-800 text-slate-100 border-t border-l border-r border-slate-700'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {labelFor(t)}
              {tab === t ? ` (${counts.current})` : ''}
            </button>
          ))}
        </nav>

        {err && (
          <p className="text-xs text-rose-400 bg-rose-950/40 border border-rose-900 rounded-lg p-3">
            Errore: {err}
          </p>
        )}

        {/* List */}
        {loading ? (
          <p className="text-sm text-slate-500">Carico…</p>
        ) : skills.length === 0 ? (
          <EmptyState tab={tab} />
        ) : (
          <ul className="space-y-3">
            {skills.map((s) => (
              <SkillCard
                key={s.id}
                skill={s}
                onEdit={() => setEditing(s)}
                onApprove={async () => {
                  try {
                    await approveSkill(s.id);
                    await refresh();
                  } catch (e) {
                    setErr((e as Error).message);
                  }
                }}
                onReject={async () => {
                  if (!window.confirm(`Disabilitare la skill ${s.name}?`)) return;
                  try {
                    await rejectSkill(s.id);
                    await refresh();
                  } catch (e) {
                    setErr((e as Error).message);
                  }
                }}
                onDelete={async () => {
                  if (
                    !window.confirm(
                      `Cancellare la skill ${s.name}? Operazione irreversibile.`,
                    )
                  )
                    return;
                  try {
                    await deleteSkill(s.id);
                    await refresh();
                  } catch (e) {
                    setErr((e as Error).message);
                  }
                }}
              />
            ))}
          </ul>
        )}

        {/* Primitive reference */}
        <PrimitiveCatalogPanel primitives={primitives} />
      </div>

      {/* Edit modal */}
      {editing && (
        <EditModal
          skill={editing}
          primitives={primitives}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await refresh();
          }}
        />
      )}
    </main>
  );
}


function labelFor(t: Tab): string {
  return t === 'pending' ? 'In attesa' : t === 'active' ? 'Attive' : 'Disabilitate';
}


function EmptyState({ tab }: { tab: Tab }) {
  const msg =
    tab === 'pending'
      ? 'Nessuna skill in attesa di approvazione.'
      : tab === 'active'
        ? 'Nessuna skill attiva al momento.'
        : 'Nessuna skill disabilitata.';
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-8 text-center">
      <p className="text-sm text-slate-400">{msg}</p>
      {tab === 'pending' && (
        <p className="text-xs text-slate-600 mt-2">
          Le nuove skill arrivano da chat utente + Skill Author. Quando uno
          chiede qualcosa di nuovo, una bozza appare qui.
        </p>
      )}
    </div>
  );
}


function SkillCard({
  skill,
  onEdit,
  onApprove,
  onReject,
  onDelete,
}: {
  skill: Skill;
  onEdit: () => void;
  onApprove: () => void;
  onReject: () => void;
  onDelete: () => void;
}) {
  const stepCount = skill.plan?.steps?.length ?? 0;
  const tools = (skill.plan?.steps ?? []).map((s) => s.tool);
  return (
    <li className="rounded-2xl bg-slate-800/50 border border-slate-700 p-4 space-y-2">
      <div className="flex items-baseline justify-between">
        <div>
          <h3 className="text-sm font-medium">
            {skill.name}{' '}
            <span className="text-xs text-slate-500">v{skill.version}</span>
          </h3>
          <p className="text-xs text-slate-400 leading-snug mt-0.5">
            {skill.description}
          </p>
        </div>
        <span
          className={`text-[10px] px-2 py-0.5 rounded-full uppercase tracking-wide ${
            skill.status === 'active'
              ? 'bg-emerald-900/40 text-emerald-300 border border-emerald-800'
              : skill.status === 'pending'
                ? 'bg-amber-900/40 text-amber-300 border border-amber-800'
                : 'bg-slate-700 text-slate-400 border border-slate-600'
          }`}
        >
          {skill.status}
        </span>
      </div>

      <div className="text-[11px] text-slate-500 flex flex-wrap gap-x-3 gap-y-1">
        <span>
          <strong className="text-slate-400">{stepCount}</strong>{' '}
          {stepCount === 1 ? 'step' : 'steps'}
        </span>
        <span>
          <strong className="text-slate-400">
            {skill.intent_examples.length}
          </strong>{' '}
          esempi intent
        </span>
        {skill.auto_authored && (
          <span className="text-slate-500">creata da Skill Author</span>
        )}
      </div>

      {tools.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {tools.map((t, i) => (
            <code
              key={i}
              className="text-[10px] bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-emerald-300"
            >
              {t}
            </code>
          ))}
        </div>
      )}

      <div className="flex gap-2 pt-1">
        <button
          type="button"
          onClick={onEdit}
          className="text-xs px-3 py-1 rounded-lg bg-slate-700 hover:bg-slate-600"
        >
          Modifica
        </button>
        {skill.status !== 'active' && (
          <button
            type="button"
            onClick={onApprove}
            className="text-xs px-3 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500"
          >
            Approva
          </button>
        )}
        {skill.status === 'active' && (
          <button
            type="button"
            onClick={onReject}
            className="text-xs px-3 py-1 rounded-lg bg-amber-700 hover:bg-amber-600"
          >
            Disabilita
          </button>
        )}
        <button
          type="button"
          onClick={onDelete}
          className="text-xs px-3 py-1 rounded-lg bg-rose-900/60 hover:bg-rose-800 ml-auto"
        >
          Cancella
        </button>
      </div>
    </li>
  );
}


function EditModal({
  skill,
  primitives,
  onClose,
  onSaved,
}: {
  skill: Skill;
  primitives: PrimitiveSpec[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [description, setDescription] = useState(skill.description);
  const [examples, setExamples] = useState(skill.intent_examples.join('\n'));
  const [slotJson, setSlotJson] = useState(
    JSON.stringify(skill.slot_extraction, null, 2),
  );
  const [planJson, setPlanJson] = useState(
    JSON.stringify(skill.plan, null, 2),
  );
  const [responseTpl, setResponseTpl] = useState(skill.response_template ?? '');
  const [fallback, setFallback] = useState(skill.fallback_response ?? '');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    setErr(null);
    setSaving(true);
    try {
      let slotObj: Record<string, unknown> | undefined;
      let planObj: Skill['plan'] | undefined;
      try {
        slotObj = JSON.parse(slotJson || '{}');
      } catch (e) {
        throw new Error(`slot_extraction: JSON non valido (${(e as Error).message})`);
      }
      try {
        planObj = JSON.parse(planJson);
      } catch (e) {
        throw new Error(`plan: JSON non valido (${(e as Error).message})`);
      }
      await patchSkill(skill.id, {
        description,
        intent_examples: examples
          .split('\n')
          .map((x) => x.trim())
          .filter(Boolean),
        slot_extraction: slotObj,
        plan: planObj,
        response_template: responseTpl || null,
        fallback_response: fallback || null,
      });
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-label="Modifica skill"
      className="fixed inset-0 z-50 bg-black/60 flex items-stretch justify-center p-3"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="px-5 py-3 border-b border-slate-800 flex items-baseline justify-between">
          <h2 className="text-sm font-medium">
            {skill.name} <span className="text-xs text-slate-500">v{skill.version}</span>
          </h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-100">
            ✕
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-5 space-y-4 text-xs">
          <Field label="Descrizione">
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5"
            />
          </Field>

          <Field label={`Esempi di intent (uno per riga, max 32)`}>
            <textarea
              rows={5}
              value={examples}
              onChange={(e) => setExamples(e.target.value)}
              placeholder={'aggiungi pasta alla spesa\nmettimi pasta in lista'}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5 font-mono"
            />
          </Field>

          <Field label="slot_extraction (JSON)">
            <textarea
              rows={4}
              spellCheck={false}
              value={slotJson}
              onChange={(e) => setSlotJson(e.target.value)}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5 font-mono"
            />
          </Field>

          <Field
            label={
              <>
                plan (JSON) — usa solo le primitive del catalogo qui sotto
              </>
            }
          >
            <textarea
              rows={12}
              spellCheck={false}
              value={planJson}
              onChange={(e) => setPlanJson(e.target.value)}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5 font-mono"
            />
          </Field>

          <Field label="response_template">
            <textarea
              rows={3}
              value={responseTpl}
              onChange={(e) => setResponseTpl(e.target.value)}
              placeholder={'Aggiunti {add.count} articoli alla spesa: {add.preview}'}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5"
            />
          </Field>

          <Field label="fallback_response (mostrato se la pipeline esplode)">
            <textarea
              rows={2}
              value={fallback}
              onChange={(e) => setFallback(e.target.value)}
              placeholder={'Mi spiace, qualcosa è andato storto.'}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5"
            />
          </Field>

          <details className="bg-slate-800/40 border border-slate-700 rounded-lg p-3">
            <summary className="cursor-pointer text-slate-300">
              Catalogo primitive ({primitives.length})
            </summary>
            <ul className="mt-2 space-y-1.5 text-[11px]">
              {primitives.map((p) => (
                <li key={p.name} className="border-l-2 border-emerald-700 pl-2">
                  <code className="text-emerald-300">{p.name}</code>
                  <span className="text-slate-500">
                    ({Object.keys(p.args_schema).join(', ')})
                  </span>
                  <p className="text-slate-400 leading-snug">{p.description}</p>
                </li>
              ))}
            </ul>
          </details>

          {err && (
            <p className="text-rose-400 bg-rose-950/40 border border-rose-900 rounded-lg p-2">
              {err}
            </p>
          )}
        </div>

        <footer className="px-5 py-3 border-t border-slate-800 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs rounded-lg bg-slate-700 hover:bg-slate-600"
          >
            Annulla
          </button>
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="px-3 py-1.5 text-xs rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40"
          >
            {saving ? 'Salvo…' : 'Salva'}
          </button>
        </footer>
      </div>
    </div>
  );
}


function Field({
  label,
  children,
}: {
  label: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-slate-400">{label}</span>
      {children}
    </label>
  );
}


function PrimitiveCatalogPanel({ primitives }: { primitives: PrimitiveSpec[] }) {
  return (
    <details className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
      <summary className="cursor-pointer text-sm text-slate-300">
        Catalogo primitive disponibili ({primitives.length})
      </summary>
      <ul className="mt-3 space-y-2 text-xs">
        {primitives.map((p) => (
          <li key={p.name} className="border-l-2 border-emerald-700 pl-3">
            <code className="text-emerald-300 font-medium">{p.name}</code>
            <code className="text-slate-500">
              ({Object.keys(p.args_schema).join(', ')})
            </code>
            <p className="text-slate-400 leading-snug mt-0.5">{p.description}</p>
            <p className="text-[10px] text-slate-600 mt-0.5">
              ritorna: {Object.keys(p.returns_schema).join(', ')}
              {p.needs_session && ' · usa la sessione'}
              {p.needs_user_id && ' · usa lo user_id corrente'}
            </p>
          </li>
        ))}
      </ul>
    </details>
  );
}
