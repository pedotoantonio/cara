// DietWeek — barre delle frequenze per categoria (coi COLORI del piano),
// adherence score, medie acqua/caffè/kcal, e generazione del resoconto
// settimanale (PDF + condivisione Telegram).

import { useEffect, useState } from 'react';

import {
  generateWeeklyReport,
  getWeek,
  type CategoryProgress,
  type Week,
  type WeeklyReport,
} from '../../api/diet';
import { Button, Card } from '../../design';

const STATE_LABEL: Record<string, string> = {
  ok: 'in linea',
  under: 'sotto target',
  warn: 'al limite',
  over: 'oltre il max',
};

export function DietWeek() {
  const [week, setWeek] = useState<Week | null>(null);
  const [report, setReport] = useState<WeeklyReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getWeek().then(setWeek).catch(() => undefined);
  }, []);

  async function makeReport(share: boolean) {
    setBusy(true);
    try {
      const r = await generateWeeklyReport({ shareTelegram: share });
      setReport(r);
    } finally {
      setBusy(false);
    }
  }

  if (!week) return <div className="text-fg-muted text-sm">Caricamento…</div>;

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-baseline justify-between mb-1">
          <h2 className="font-semibold">Frequenze della settimana</h2>
          <span className="text-2xs text-fg-muted">
            {fmt(week.week_start)}–{fmt(week.week_end)}
          </span>
        </div>
        <div className="text-3xl font-bold mb-4">
          {week.adherence_score.toFixed(0)}%
          <span className="text-sm font-normal text-fg-muted ml-2">aderenza</span>
        </div>

        <div className="space-y-3">
          {week.categories.map((c) => (
            <FrequencyBar key={c.category} c={c} />
          ))}
        </div>
      </Card>

      <div className="grid grid-cols-3 gap-3 text-center">
        <Stat label="kcal/giorno" value={week.avg_kcal_per_day ? `≈${week.avg_kcal_per_day}` : '—'} hint="indicativo" />
        <Stat label="acqua/giorno" value={week.avg_water_ml ? `${(week.avg_water_ml / 1000).toFixed(1)}L` : '—'} />
        <Stat label="caffè/giorno" value={week.avg_coffee != null ? `${week.avg_coffee}` : '—'} />
      </div>

      {week.notes.length > 0 && (
        <Card>
          <h3 className="font-semibold text-sm mb-2">Note</h3>
          <ul className="space-y-1 text-sm text-fg-muted">
            {week.notes.map((n, i) => (
              <li key={i}>• {n}</li>
            ))}
          </ul>
        </Card>
      )}

      {/* Resoconto */}
      <Card>
        <h3 className="font-semibold mb-2">Resoconto settimanale</h3>
        <div className="flex gap-2">
          <Button variant="primary" fullWidth loading={busy} onClick={() => makeReport(false)}>
            Genera
          </Button>
          <Button variant="ghost" fullWidth loading={busy} onClick={() => makeReport(true)}>
            Condividi su Telegram
          </Button>
        </div>

        {report && (
          <div className="mt-4 space-y-3">
            <pre className="whitespace-pre-wrap text-sm bg-surface2 rounded-xl p-3 font-sans">
              {stripHtml(report.telegram_text)}
            </pre>
            <div className="flex gap-2">
              {report.pdf_url && (
                <a href={report.pdf_url} target="_blank" rel="noreferrer" className="flex-1">
                  <Button variant="ghost" fullWidth>
                    Scarica PDF
                  </Button>
                </a>
              )}
              <Button
                variant="ghost"
                fullWidth
                onClick={() => {
                  navigator.clipboard?.writeText(stripHtml(report.telegram_text));
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }}
              >
                {copied ? 'Copiato ✓' : 'Copia testo'}
              </Button>
            </div>
            {report.sent_to_telegram && (
              <p className="text-xs text-ok">Inviato al bot Telegram ✓</p>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

function FrequencyBar({ c }: { c: CategoryProgress }) {
  const max = Math.max(c.target_max ?? 4, c.consumed, 1);
  const pct = Math.min(100, (c.consumed / max) * 100);
  const targetMinPct = c.target_min != null ? (c.target_min / max) * 100 : null;
  const targetMaxPct = c.target_max != null ? (c.target_max / max) * 100 : null;
  return (
    <div>
      <div className="flex justify-between items-baseline mb-1">
        <span className="text-sm font-medium capitalize">{c.category}</span>
        <span className="text-xs text-fg-muted">
          {c.consumed} / {c.target_min ?? 0}-{c.target_max ?? '?'} · {STATE_LABEL[c.state]}
        </span>
      </div>
      <div className="relative h-3 rounded-full bg-surface2 overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: c.color }}
        />
        {/* target window markers */}
        {targetMinPct != null && (
          <span className="absolute top-0 bottom-0 w-px bg-fg/30" style={{ left: `${targetMinPct}%` }} />
        )}
        {targetMaxPct != null && (
          <span className="absolute top-0 bottom-0 w-px bg-fg/40" style={{ left: `${targetMaxPct}%` }} />
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="py-3">
      <div className="text-xl font-bold">{value}</div>
      <div className="text-2xs text-fg-muted">{label}</div>
      {hint && <div className="text-2xs text-fg-muted/70">{hint}</div>}
    </Card>
  );
}

function fmt(d: string): string {
  const [, m, day] = d.split('-');
  return `${day}/${m}`;
}

function stripHtml(s: string): string {
  return s.replace(/<[^>]+>/g, '');
}
