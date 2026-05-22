import { useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeft,
  Wallet as WalletIcon,
  CheckSquare,
  ShoppingCart,
  Note,
  Sun,
  Users,
  Sparkle,
  Newspaper,
  MusicNote,
  Bell,
  CurrencyEur,
  GraduationCap,
  Clock,
} from '@phosphor-icons/react';
import {
  Card,
  CardSubtitle,
  CardTitle,
  Skeleton,
} from '@/design/components';
import { useAvatarStore } from '@/state/avatar';
import { getLayout, renderWidgets, type WalletWidget } from '@/api/wallet';

function detectSurface(): 'wall' | 'mobile' | 'desktop' {
  if (typeof window === 'undefined') return 'mobile';
  if (window.matchMedia('(min-width: 1024px)').matches) return 'desktop';
  return 'mobile';
}

const ICON: Record<string, { Icon: typeof CheckSquare; accent: string }> = {
  today_summary: { Icon: Clock, accent: 'text-accent-coral' },
  tasks_mine: { Icon: CheckSquare, accent: 'text-accent-mint' },
  shopping_quick: { Icon: ShoppingCart, accent: 'text-accent-rose' },
  notes_recent: { Icon: Note, accent: 'text-accent-sun' },
  weather_now: { Icon: Sun, accent: 'text-accent-sky' },
  presence: { Icon: Users, accent: 'text-accent-grass' },
  quick_actions: { Icon: Sparkle, accent: 'text-accent-lilac' },
  budget_month: { Icon: CurrencyEur, accent: 'text-accent-mint' },
  kids_homework: { Icon: GraduationCap, accent: 'text-accent-lilac' },
  routine_next: { Icon: Clock, accent: 'text-accent-coral' },
  cara_quote: { Icon: Sparkle, accent: 'text-accent-lilac' },
  news_brief: { Icon: Newspaper, accent: 'text-accent-clay' },
  radio_now_playing: { Icon: MusicNote, accent: 'text-accent-clay' },
  reminders_upcoming: { Icon: Bell, accent: 'text-accent-coral' },
  reminders_list: { Icon: Bell, accent: 'text-accent-coral' },
};

function WidgetRenderer({ widget }: { widget: WalletWidget }) {
  const meta = ICON[widget.kind] ?? { Icon: WalletIcon, accent: 'text-text-secondary' };
  const Icon = meta.Icon;
  const data = (widget.data as Record<string, unknown>) ?? {};
  // Best-effort rendering: titles + summary fields
  const title = (data.title as string) ?? widget.title ?? widget.kind.replaceAll('_', ' ');
  const subtitle = (data.subtitle as string) ?? (data.summary as string) ?? '';

  // Specific render hints by kind
  if (widget.kind === 'weather_now') {
    const temp = data.temperature as number | undefined;
    const label = (data.label as string) ?? 'Meteo';
    const city = (data.city as string) ?? '';
    return (
      <Card padding="lg" elevation={1}>
        <div className="flex items-center gap-3">
          <Icon size={32} weight="duotone" className={meta.accent} />
          <div className="flex-1 min-w-0">
            <CardTitle>{city ? `Meteo · ${city}` : 'Meteo'}</CardTitle>
            <p className="font-display text-2xl text-text-primary mt-1">
              {temp != null ? Math.round(temp) + '°' : '—'}
            </p>
            <CardSubtitle>{label}</CardSubtitle>
          </div>
        </div>
      </Card>
    );
  }

  if (widget.kind === 'tasks_mine' || widget.kind === 'shopping_quick') {
    const items = (data.items as Array<{ title: string }>) ?? [];
    return (
      <Card padding="lg" elevation={1}>
        <div className="flex items-center gap-3 mb-2">
          <Icon size={24} weight="duotone" className={meta.accent} />
          <CardTitle>{title}</CardTitle>
        </div>
        {items.length === 0 ? (
          <CardSubtitle>Nessun elemento</CardSubtitle>
        ) : (
          <ul className="space-y-1">
            {items.slice(0, 5).map((it, i) => (
              <li key={i} className="text-sm">
                • {it.title}
              </li>
            ))}
            {items.length > 5 && (
              <li className="text-xs text-text-muted">+{items.length - 5} altri</li>
            )}
          </ul>
        )}
      </Card>
    );
  }

  if (widget.kind === 'cara_quote') {
    const quote = (data.quote as string) ?? (data.text as string) ?? '';
    return (
      <Card padding="lg" elevation={1} surface="surface">
        <div className="flex items-start gap-3">
          <Icon size={24} weight="duotone" className={meta.accent} />
          <div className="flex-1">
            <p className="font-display text-md text-text-primary italic">"{quote || '…'}"</p>
          </div>
        </div>
      </Card>
    );
  }

  // Generic fallback
  return (
    <Card padding="lg" elevation={1}>
      <div className="flex items-center gap-3">
        <Icon size={24} weight="duotone" className={meta.accent} />
        <div className="flex-1 min-w-0">
          <CardTitle>{title}</CardTitle>
          {subtitle && <CardSubtitle>{subtitle}</CardSubtitle>}
          {widget.error && (
            <CardSubtitle className="text-accent-coral">Errore: {widget.error}</CardSubtitle>
          )}
        </div>
      </div>
    </Card>
  );
}

export function WalletPage() {
  const navigate = useNavigate();
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  const surface = useMemo(() => detectSurface(), []);

  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'happy',
      glowAccent: 'sun',
      caption: null,
      context: 'me:wallet',
    });
  }, [setAvatar]);

  const layoutQ = useQuery({
    queryKey: ['wallet.layout', surface],
    queryFn: () => getLayout(surface),
    staleTime: 60_000,
  });

  const widgetsQ = useQuery({
    queryKey: ['widgets.render', layoutQ.data?.widget_ids ?? []],
    queryFn: () => renderWidgets(layoutQ.data?.widget_ids ?? []),
    enabled: !!layoutQ.data && layoutQ.data.widget_ids.length > 0,
    staleTime: 30_000,
  });

  return (
    <div className="container-app py-4 space-y-4">
      <header className="flex items-center gap-2">
        <button onClick={() => navigate('/me')} className="p-2 -m-2" aria-label="Indietro">
          <ArrowLeft size={20} />
        </button>
        <h1 className="font-display text-2xl">Wallet</h1>
      </header>

      <Card padding="base" surface="surface" elevation={0}>
        <CardSubtitle>
          Widget personalizzati per <strong>{surface}</strong>. Per modificare l'ordine usa
          la v1 (per ora).
        </CardSubtitle>
      </Card>

      {layoutQ.isLoading && <Skeleton className="h-32 w-full" />}

      {layoutQ.data && layoutQ.data.widget_ids.length === 0 && (
        <Card padding="lg" surface="surface" elevation={0}>
          <CardTitle>Nessun widget configurato</CardTitle>
          <CardSubtitle className="mt-1">
            Apri /admin (v1) → Wallet per scegliere un preset.
          </CardSubtitle>
        </Card>
      )}

      {widgetsQ.isLoading && <Skeleton className="h-40 w-full" />}

      <div className="space-y-3">
        {widgetsQ.data?.map((w) => (
          <WidgetRenderer key={w.id} widget={w} />
        ))}
      </div>
    </div>
  );
}
