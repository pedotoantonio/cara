// Wallet — la pagina "Wallet" mostra un layout di widget personalizzabile
// per surface (mobile/desktop). Le presets coprono i 4 ruoli familiari.
//
// L'utente vede subito il proprio set; può
//   - rimuovere widget (X sull'angolo)
//   - applicare un preset (sheet "Preset")
//   - aggiungere widget (sheet "Aggiungi" — catalogo)
//   - resettare al default

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Badge,
  BottomSheet,
  Button,
  Card,
  CardSubtitle,
  CardTitle,
  Icon,
  cn,
  useToast,
} from '../design';
import {
  applyPreset,
  getLayout,
  listPresets,
  listWidgetCatalog,
  putLayout,
  renderWidgets,
  resetLayout,
  type Layout,
  type LayoutItem,
  type RenderedWidget,
  type Surface,
  type WalletPreset,
  type WidgetCatalogEntry,
} from '../api/wallet';
import { WidgetCard } from '../components/widgets/WidgetCard';

function pickSurface(): Surface {
  if (typeof window === 'undefined') return 'mobile';
  const w = window.innerWidth;
  if (w >= 1280) return 'desktop';
  return 'mobile';
}

export function WalletPage() {
  const toast = useToast();
  const [surface, setSurface] = useState<Surface>(() => pickSurface());
  const [layout, setLayout] = useState<Layout | null>(null);
  const [rendered, setRendered] = useState<RenderedWidget[]>([]);
  const [loadingLayout, setLoadingLayout] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [presets, setPresets] = useState<WalletPreset[]>([]);
  const [catalog, setCatalog] = useState<WidgetCatalogEntry[]>([]);

  const [presetOpen, setPresetOpen] = useState(false);
  const [catalogOpen, setCatalogOpen] = useState(false);

  // Initial: layout + presets + catalog in parallel.
  useEffect(() => {
    let cancelled = false;
    setLoadingLayout(true);
    Promise.all([getLayout(surface), listPresets(), listWidgetCatalog()])
      .then(([l, ps, cat]) => {
        if (cancelled) return;
        setLayout(l);
        setPresets(ps);
        setCatalog(cat);
      })
      .catch(() => toast.push({
        kind: 'alert',
        title: 'Wallet non disponibile',
        body: 'Il backend non risponde, riprova fra un momento.',
      }))
      .finally(() => { if (!cancelled) setLoadingLayout(false); });
    return () => { cancelled = true; };
  }, [surface, toast]);

  // Whenever layout changes, re-render its widgets.
  const refreshRender = useCallback(async (l: Layout) => {
    if (!l || l.items.length === 0) {
      setRendered([]);
      return;
    }
    setRefreshing(true);
    try {
      const ids = l.items.map(it => it.widget_id);
      const r = await renderWidgets(ids, surface, 'medium');
      setRendered(r.items);
    } catch {
      // keep stale rendered values silently — better than blank flash
    } finally {
      setRefreshing(false);
    }
  }, [surface]);

  useEffect(() => {
    if (layout) void refreshRender(layout);
  }, [layout, refreshRender]);

  // --- Actions ---

  const applyPresetAction = useCallback(async (slug: string) => {
    setPresetOpen(false);
    try {
      const l = await applyPreset(slug, surface);
      setLayout(l);
      const found = presets.find(p => p.slug === slug);
      toast.push({
        kind: 'celebrate',
        title: `Preset "${found?.label ?? slug}" applicato`,
        body: 'Il tuo Wallet ha cambiato veste.',
      });
    } catch {
      toast.push({ kind: 'alert', title: 'Non sono riuscita ad applicare il preset' });
    }
  }, [surface, presets, toast]);

  const removeWidget = useCallback(async (widget_id: string) => {
    if (!layout) return;
    const next: LayoutItem[] = layout.items.filter(it => it.widget_id !== widget_id);
    try {
      const l = await putLayout(surface, next);
      setLayout(l);
    } catch {
      toast.push({ kind: 'alert', title: 'Salvataggio fallito' });
    }
  }, [layout, surface, toast]);

  const addWidget = useCallback(async (widget_id: string) => {
    if (!layout) return;
    if (layout.items.some(it => it.widget_id === widget_id)) {
      setCatalogOpen(false);
      return;
    }
    const next: LayoutItem[] = [
      ...layout.items,
      { widget_id, size: 'medium', config: {} },
    ];
    setCatalogOpen(false);
    try {
      const l = await putLayout(surface, next);
      setLayout(l);
      toast.push({ kind: 'ok', title: 'Aggiunto al Wallet' });
    } catch {
      toast.push({ kind: 'alert', title: 'Salvataggio fallito' });
    }
  }, [layout, surface, toast]);

  const reset = useCallback(async () => {
    try {
      await resetLayout(surface);
      const l = await getLayout(surface);
      setLayout(l);
      toast.push({ kind: 'ok', title: 'Wallet ripristinato' });
    } catch {
      toast.push({ kind: 'alert', title: 'Reset fallito' });
    }
  }, [surface, toast]);

  const isCustom = layout && !layout.is_default;
  const presetLabel = layout?.preset === 'custom'
    ? 'personalizzato'
    : (layout?.preset ?? 'default');

  const widgetIdSet = useMemo(
    () => new Set(layout?.items.map(it => it.widget_id) ?? []),
    [layout],
  );

  // --- UI ---

  return (
    <div className="px-5 md:px-8 max-w-5xl mx-auto pb-8">
      {/* Page header */}
      <div className="flex items-end justify-between gap-3 mb-5">
        <div>
          <h1 className="font-display text-3xl md:text-4xl text-fg leading-tight">
            Wallet
          </h1>
          <p className="text-sm text-fg-soft mt-1">
            La tua casa, riassunta in un colpo d'occhio.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={isCustom ? 'accent' : 'muted'} dot>
            {presetLabel}
          </Badge>
        </div>
      </div>

      {/* Surface selector — wall/mobile/desktop tabs */}
      <SurfaceTabs current={surface} onChange={setSurface} />

      {/* Quick actions */}
      <div className="flex flex-wrap gap-2 mb-5 mt-4">
        <Button
          variant="surface"
          size="sm"
          iconLeft="sparkle"
          onClick={() => setPresetOpen(true)}
        >
          Preset
        </Button>
        <Button
          variant="surface"
          size="sm"
          iconLeft="plus"
          onClick={() => setCatalogOpen(true)}
        >
          Aggiungi
        </Button>
        {isCustom && (
          <Button variant="quiet" size="sm" iconLeft="close" onClick={reset}>
            Ripristina
          </Button>
        )}
        {refreshing && (
          <span className="ml-auto text-xs text-fg-muted self-center animate-breathe">
            aggiornamento…
          </span>
        )}
      </div>

      {/* Widget grid */}
      {loadingLayout ? (
        <SkeletonGrid />
      ) : rendered.length === 0 ? (
        <EmptyState onPickPreset={() => setPresetOpen(true)} />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 md:gap-4">
          {rendered.map(w => (
            <WidgetCard
              key={w.widget_id}
              data={w}
              onRemove={() => removeWidget(w.widget_id)}
            />
          ))}
        </div>
      )}

      {/* ── Preset sheet ─────────────────────────────────── */}
      <BottomSheet
        open={presetOpen}
        onClose={() => setPresetOpen(false)}
        title="Cambia preset"
        subtitle="Quattro modi diversi di guardare la stessa casa."
        size="md"
      >
        <div className="space-y-3 pb-2">
          {presets.map(p => (
            <button
              key={p.slug}
              type="button"
              onClick={() => applyPresetAction(p.slug)}
              className={cn(
                'w-full text-left rounded-xl p-4 transition-all',
                'bg-surface1 hover:bg-surface2 active:scale-[0.99]',
                'ring-1 ring-fg/8 hover:ring-accent/40',
              )}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="font-display text-md text-fg">{p.label}</div>
                <Icon name="send" size={16} className="text-fg-muted" />
              </div>
              <p className="text-xs text-fg-soft mt-1 leading-relaxed">
                {p.description}
              </p>
            </button>
          ))}
        </div>
      </BottomSheet>

      {/* ── Catalog sheet ────────────────────────────────── */}
      <BottomSheet
        open={catalogOpen}
        onClose={() => setCatalogOpen(false)}
        title="Aggiungi un widget"
        subtitle="Tocca per appoggiarlo nel Wallet."
        size="lg"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pb-2">
          {catalog.map(w => {
            const already = widgetIdSet.has(w.id);
            return (
              <button
                key={w.id}
                type="button"
                disabled={already}
                onClick={() => addWidget(w.id)}
                className={cn(
                  'flex items-center justify-between gap-3 rounded-xl p-3.5 text-left transition-all',
                  'bg-surface1 hover:bg-accent/8',
                  'disabled:opacity-50 disabled:bg-surface1 disabled:cursor-not-allowed',
                )}
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium text-fg truncate">{w.title}</div>
                  <div className="text-2xs text-fg-muted mt-0.5">
                    aggiornato ogni {Math.max(15, w.refresh_interval_s)}s
                  </div>
                </div>
                <span className={cn(already ? 'text-fg-muted' : 'text-accent')}>
                  <Icon name={already ? 'check' : 'plus'} size={20} />
                </span>
              </button>
            );
          })}
          {catalog.length === 0 && (
            <p className="text-sm text-fg-muted col-span-full text-center py-6">
              Nessun widget disponibile per il tuo ruolo.
            </p>
          )}
        </div>
      </BottomSheet>
    </div>
  );
}

// ── Pieces ─────────────────────────────────────────────────────

function SurfaceTabs({
  current, onChange,
}: {
  current: Surface;
  onChange: (s: Surface) => void;
}) {
  const tabs: Array<{ s: Surface; label: string }> = [
    { s: 'mobile',  label: 'Mobile' },
    { s: 'desktop', label: 'Desktop' },
    { s: 'wall',    label: 'Parete' },
  ];
  return (
    <div className="inline-flex rounded-pill bg-surface1 p-1 ring-1 ring-fg/8">
      {tabs.map(t => (
        <button
          key={t.s}
          type="button"
          onClick={() => onChange(t.s)}
          className={cn(
            'px-3.5 h-8 rounded-pill text-xs font-medium transition-all',
            current === t.s
              ? 'bg-accent text-ivory shadow-warm'
              : 'text-fg-soft hover:text-fg',
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 md:gap-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <Card key={i} variant="flat" className="space-y-3">
          <div className="h-4 w-1/3 rounded-pill bg-surface2 animate-breathe" />
          <div className="h-3 w-2/3 rounded-pill bg-surface2 animate-breathe" />
          <div className="h-3 w-1/2 rounded-pill bg-surface2 animate-breathe" />
        </Card>
      ))}
    </div>
  );
}

function EmptyState({ onPickPreset }: { onPickPreset: () => void }) {
  return (
    <Card variant="raised" className="text-center py-10">
      <CardTitle className="!text-2xl">Wallet vuoto</CardTitle>
      <CardSubtitle className="!mt-2">
        Aggiungi qualche widget o scegli un preset.
      </CardSubtitle>
      <div className="mt-5">
        <Button variant="primary" size="md" iconLeft="sparkle" onClick={onPickPreset}>
          Scegli un preset
        </Button>
      </div>
    </Card>
  );
}
