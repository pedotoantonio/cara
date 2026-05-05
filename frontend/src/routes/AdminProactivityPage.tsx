// /admin/proactivity — pannello regole proattive (toggle + run now).

import { useEffect, useState } from 'react';

import {
  RuleInfo,
  SuggestionPreview,
  listRules,
  runNow,
  toggleRule,
} from '../api/proactivity';
import {
  Badge,
  Button,
  Card,
  CardSubtitle,
  CardTitle,
  Icon,
  cn,
  useToast,
} from '../design';

const PRIORITY_LABELS: Record<number, { label: string; tone: 'muted' | 'accent' | 'celebrate' | 'alert' }> = {
  10: { label: 'bassa', tone: 'muted' },
  30: { label: 'normale', tone: 'accent' },
  60: { label: 'alta', tone: 'celebrate' },
  90: { label: 'urgente', tone: 'alert' },
};


function timeAgo(iso: string | null): string {
  if (!iso) return 'mai';
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const min = Math.floor(diff / 60_000);
  if (min < 1) return 'pochi secondi fa';
  if (min < 60) return `${min} min fa`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h fa`;
  const days = Math.floor(h / 24);
  return `${days}g fa`;
}


export function AdminProactivityPage() {
  const toast = useToast();
  const [rules, setRules] = useState<RuleInfo[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [preview, setPreview] = useState<SuggestionPreview[] | null>(null);

  async function refresh() {
    try {
      setRules(await listRules());
    } catch (e) {
      toast.push({ kind: 'alert', title: 'Lista regole non disponibile' });
    }
  }

  useEffect(() => { void refresh(); }, []);

  async function flip(rule: RuleInfo) {
    setBusyId(rule.rule_id);
    try {
      await toggleRule(rule.rule_id, !rule.enabled);
      setRules(cur => cur?.map(r => r.rule_id === rule.rule_id ? { ...r, enabled: !rule.enabled } : r) ?? null);
    } catch {
      toast.push({ kind: 'alert', title: 'Toggle fallito' });
    } finally {
      setBusyId(null);
    }
  }

  async function runPreview() {
    setPreviewBusy(true);
    setPreview(null);
    try {
      const r = await runNow();
      setPreview(r.suggestions);
      if (r.count === 0) {
        toast.push({
          kind: 'info',
          title: 'Nessun suggerimento',
          body: 'Nessuna regola si è attivata in questo momento (cooldown / orario).',
        });
      } else {
        toast.push({
          kind: 'celebrate',
          title: `${r.count} suggerimenti`,
          body: 'Vedi sotto cosa Cara avrebbe inviato.',
        });
      }
    } catch {
      toast.push({ kind: 'alert', title: 'Run fallito' });
    } finally {
      setPreviewBusy(false);
    }
  }

  return (
    <div className="px-5 md:px-8 max-w-3xl mx-auto pb-8">
      <div className="mb-5">
        <h1 className="font-display text-3xl md:text-4xl text-fg leading-tight">
          Proattività · Admin
        </h1>
        <p className="text-sm text-fg-soft mt-1">
          Le regole che rendono Cara "viva". Disattivane qualcuna se le notifiche
          sono troppe; tieni solo quelle che servono davvero.
        </p>
      </div>

      <Card variant="raised" className="mb-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="!text-base">Test rapido</CardTitle>
            <CardSubtitle>
              Esegui il motore proattivo qui e ora; vedrai cosa avrebbe inviato.
            </CardSubtitle>
          </div>
          <Button
            variant="surface"
            size="sm"
            iconLeft="spark"
            loading={previewBusy}
            onClick={() => void runPreview()}
          >
            Esegui adesso
          </Button>
        </div>

        {preview && preview.length > 0 && (
          <div className="mt-4 space-y-2">
            {preview.map(s => {
              const pri = PRIORITY_LABELS[s.priority] ?? PRIORITY_LABELS[30];
              return (
                <div
                  key={s.rule_id}
                  className="rounded-md bg-surface2 p-3 ring-1 ring-fg/8"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <code className="text-2xs text-fg-muted">{s.rule_id}</code>
                    <Badge tone={pri.tone} size="sm">{pri.label}</Badge>
                  </div>
                  <p className="text-sm text-fg leading-snug">{s.text}</p>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <h2 className="text-xs uppercase tracking-wider text-fg-muted px-1 mb-2">
        Regole registrate
      </h2>

      {rules === null && (
        <Card variant="flat" className="animate-breathe h-24" />
      )}

      {rules !== null && (
        <div className="space-y-2">
          {rules.map(rule => (
            <Card
              key={rule.rule_id}
              variant={rule.enabled ? 'raised' : 'outline'}
              className={cn(rule.enabled ? '' : 'opacity-70')}
            >
              <div className="flex items-start gap-3">
                <button
                  type="button"
                  onClick={() => void flip(rule)}
                  disabled={busyId === rule.rule_id}
                  aria-label={rule.enabled ? 'Disattiva' : 'Attiva'}
                  className={cn(
                    'shrink-0 w-12 h-7 rounded-pill p-0.5 transition-all',
                    rule.enabled ? 'bg-accent' : 'bg-surface2',
                  )}
                >
                  <span
                    className={cn(
                      'block h-6 w-6 rounded-pill bg-ivory shadow-soft transition-all duration-180 ease-spring',
                      rule.enabled ? 'translate-x-5' : 'translate-x-0',
                    )}
                  />
                </button>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <code className="font-mono text-sm text-fg font-medium">
                      {rule.rule_id}
                    </code>
                    <Badge tone="muted" size="sm">
                      ogni {rule.cooldown_hours}h
                    </Badge>
                    {rule.last_fired_at && (
                      <span className="text-2xs text-fg-muted">
                        · ultimo {timeAgo(rule.last_fired_at)}
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-fg-soft mt-1 leading-snug">
                    {rule.description || 'Senza descrizione.'}
                  </p>
                </div>

                <Icon
                  name={rule.enabled ? 'check' : 'close'}
                  size={16}
                  className={cn('shrink-0 mt-1', rule.enabled ? 'text-ok' : 'text-fg-muted')}
                />
              </div>
            </Card>
          ))}

          {rules.length === 0 && (
            <Card variant="outline" className="text-center py-8 text-sm text-fg-muted">
              Nessuna regola registrata. (Controlla il backend.)
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
