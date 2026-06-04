// Widget renderer — switch su `kind`. Allinea con le shapes reali del backend.

import { Link } from 'react-router-dom';
import type { RenderedWidget } from '../../api/wallet';
import { Card, CardSubtitle, Icon, type IconName, cn } from '../../design';

interface Props {
  data: RenderedWidget;
  onRemove?: () => void;
}

// Widget id → icona suggestiva.
const ICON_BY_ID: Record<string, IconName> = {
  today_summary: 'sun',
  tasks_mine: 'task',
  shopping_quick: 'shopping',
  notes_recent: 'note',
  weather_now: 'sun',
  presence: 'family',
  presence_home: 'family',
  voice_quick: 'mic',
  budget_month: 'budget',
  kids_homework: 'task',
  habit_next: 'habit',
  routine_next: 'habit',
  cara_quote: 'sparkle',
  news_brief: 'news',
  radio_now_playing: 'radio',
  now_playing: 'radio',
  diet_summary: 'heart',
};

export function WidgetCard({ data, onRemove }: Props) {
  const icon = ICON_BY_ID[data.widget_id] ?? 'spark';
  const isError = !!data.error;

  const inner = (
    <>
      <header className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className={cn('shrink-0', isError ? 'text-fg-muted' : 'text-accent')}>
            <Icon name={icon} size={18} />
          </span>
          <h3 className="font-display text-md text-fg leading-tight truncate">
            {data.title || data.widget_id}
          </h3>
        </div>
        {onRemove && <RemoveButton onClick={onRemove} />}
      </header>
      <div className="mt-3">
        {isError ? (
          <CardSubtitle className="!mt-0 text-alert">⚠ {data.error}</CardSubtitle>
        ) : (
          <WidgetBody data={data} />
        )}
      </div>
    </>
  );

  // Deep link wraps the whole card if present (and not in error). Plain div otherwise.
  if (!isError && data.deep_link) {
    return (
      <Card variant="raised" hoverable padded={false}>
        <Link to={data.deep_link} className="block p-5">
          {inner}
        </Link>
      </Card>
    );
  }

  return <Card variant={isError ? 'outline' : 'raised'}>{inner}</Card>;
}

function RemoveButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); onClick(); }}
      className="text-fg-muted hover:text-alert p-1 -m-1 rounded-pill hover:bg-surface1 transition shrink-0"
      aria-label="Rimuovi"
    >
      <Icon name="close" size={16} />
    </button>
  );
}

function WidgetBody({ data }: { data: RenderedWidget }) {
  switch (data.kind) {
    case 'metric':       return <MetricView body={data.body} />;
    case 'list':         return <ListView body={data.body} />;
    case 'summary':      return <SummaryView body={data.body} />;
    case 'checklist':    return <ChecklistView body={data.body} />;
    case 'presence':     return <PresenceView body={data.body} />;
    case 'action_grid':  return <ActionGridView body={data.body} />;
    case 'now_playing':  return <NowPlayingView body={data.body} />;
    case 'weather':      return <WeatherView body={data.body} />;
    case 'quote':        return <QuoteView body={data.body} />;
    case 'diet_summary': return <DietSummaryView body={data.body} />;
    default:             return <FallbackView body={data.body} />;
  }
}

// ── Sub-views ─────────────────────────────────────────────────

function MetricView({ body }: { body: Record<string, unknown> }) {
  // Weather-style "available: false" → friendly empty state.
  if (body.available === false) {
    const reason = (body.reason as string | undefined) ?? 'Posizione non configurata.';
    return <p className="text-sm text-fg-muted">{reason}</p>;
  }
  const value = String((body.value as string | number | null) ?? '—');
  const label = String((body.label as string | null) ?? '');
  const sub = body.sub as string | undefined;
  return (
    <div>
      <div className="font-display text-3xl text-fg leading-none">{value}</div>
      {label && <div className="text-xs text-fg-soft mt-1">{label}</div>}
      {sub && <div className="text-2xs text-fg-muted mt-1">{sub}</div>}
    </div>
  );
}

interface RawListItem {
  id?: string | number;
  title?: string;
  subtitle?: string;
  meta?: string;
  due_unix?: number | null;
  done?: boolean;
}

function ListView({ body }: { body: Record<string, unknown> }) {
  const rawItems = (body.items ?? body.tasks ?? body.notes ?? body.list) as RawListItem[] | undefined;
  const items = Array.isArray(rawItems) ? rawItems.slice(0, 6) : [];
  const empty = (body.empty as string | null) ?? 'Niente per ora.';
  if (items.length === 0) {
    return <p className="text-sm text-fg-muted">{empty}</p>;
  }
  return (
    <ul className="divide-y divide-fg/8 -my-1">
      {items.map((it, i) => {
        const title = String(it.title ?? '—');
        const sub = it.subtitle ?? null;
        const meta = it.meta ?? formatDue(it.due_unix);
        const done = it.done === true;
        return (
          <li key={it.id ?? i} className="py-2">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0 flex items-center gap-2">
                {done && <Icon name="check" size={14} className="text-ok shrink-0" />}
                <div className="min-w-0">
                  <div className={cn('text-sm truncate', done ? 'text-fg-muted line-through' : 'text-fg')}>
                    {title}
                  </div>
                  {sub && <div className="text-2xs text-fg-muted truncate">{sub}</div>}
                </div>
              </div>
              {meta && <div className="text-2xs text-fg-soft shrink-0">{meta}</div>}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function ChecklistView({ body }: { body: Record<string, unknown> }) {
  const rawItems = body.items as Array<{ id?: string; title?: string; qty?: string | number | null }> | undefined;
  const items = Array.isArray(rawItems) ? rawItems.slice(0, 6) : [];
  const total = body.total_unchecked as number | undefined;
  if (items.length === 0) {
    return <p className="text-sm text-fg-muted">La lista è vuota.</p>;
  }
  return (
    <div>
      <ul className="space-y-1.5">
        {items.map((it, i) => (
          <li key={it.id ?? i} className="flex items-center gap-2.5 text-sm">
            <span className="h-4 w-4 rounded-pill ring-1 ring-fg/20 shrink-0" />
            <span className="text-fg flex-1 truncate">{it.title ?? '—'}</span>
            {it.qty != null && it.qty !== '' && (
              <span className="text-2xs text-fg-muted">{String(it.qty)}</span>
            )}
          </li>
        ))}
      </ul>
      {typeof total === 'number' && total > items.length && (
        <p className="text-2xs text-fg-muted mt-2.5">
          + altri {total - items.length} da prendere
        </p>
      )}
    </div>
  );
}

function SummaryView({ body }: { body: Record<string, unknown> }) {
  // Optional free text.
  const text = (body.text ?? body.message) as string | undefined;
  // Optional structured stats (today_summary returns flat keys).
  const flatStats: Array<{ label: string; value: string }> = [];

  const knownLabels: Record<string, string> = {
    tasks_today: 'task oggi',
    tasks_overdue: 'in ritardo',
    present_count: 'in casa',
    shopping_open: 'spesa',
    notes_today: 'note',
  };

  for (const [k, v] of Object.entries(body)) {
    if (k === 'text' || k === 'message' || k === 'stats') continue;
    if (v === null || v === undefined) continue;
    if (typeof v === 'object') continue;
    const label = knownLabels[k] ?? k.replace(/_/g, ' ');
    flatStats.push({ label, value: String(v) });
  }

  // Explicit stats array (other widgets may use it).
  const stats = (body.stats as Array<{ label: string; value: string }> | undefined) ?? flatStats;

  if (!text && stats.length === 0) {
    return <p className="text-sm text-fg-muted">Tutto tranquillo.</p>;
  }

  return (
    <div className="space-y-2">
      {text && <p className="text-sm text-fg leading-relaxed">{text}</p>}
      {stats.length > 0 && (
        <div className={cn(
          'grid gap-3',
          stats.length === 1 ? 'grid-cols-1' :
          stats.length === 2 ? 'grid-cols-2' : 'grid-cols-3',
          text && 'mt-2 pt-2 border-t border-fg/8',
        )}>
          {stats.slice(0, 3).map((s, i) => (
            <div key={i}>
              <div className="font-display text-2xl text-fg leading-none">{s.value}</div>
              <div className="text-2xs text-fg-muted mt-1 capitalize">{s.label}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PresenceView({ body }: { body: Record<string, unknown> }) {
  const people = (body.people as Array<{ name?: string }>) ?? [];
  const count = (body.count as number | undefined) ?? people.length;
  if (count === 0) {
    return <p className="text-sm text-fg-muted">La casa è in pausa.</p>;
  }
  return (
    <div className="space-y-2">
      <div className="font-display text-2xl text-fg leading-none">
        {count} {count === 1 ? 'persona' : 'persone'}
      </div>
      {people.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {people.slice(0, 6).map((p, i) => (
            <span
              key={i}
              className="text-2xs bg-ok/12 text-ok rounded-pill px-2 py-0.5"
            >
              {p.name ?? '—'}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

interface QuickAction {
  id?: string;
  label: string;
  icon?: string;       // matches IconName when possible (plus, shopping, note, mic, ...)
  deep_link?: string;  // route to navigate to when tapped
}

function ActionGridView({ body }: { body: Record<string, unknown> }) {
  const actions = (body.actions as QuickAction[] | undefined) ?? [];
  if (actions.length === 0) {
    return <p className="text-sm text-fg-muted">Niente azioni rapide.</p>;
  }
  return (
    <div className="grid grid-cols-2 gap-2">
      {actions.slice(0, 4).map((a, i) => {
        const iconName = (a.icon ?? 'plus') as IconName;
        const inner = (
          <span className="flex items-center justify-center gap-1.5">
            <Icon name={iconName} size={16} />
            <span>{a.label}</span>
          </span>
        );
        const cls =
          'block bg-surface2 hover:bg-accent/12 active:scale-95 ' +
          'rounded-md py-2.5 text-sm font-medium transition text-center';
        if (a.deep_link) {
          // Outer Link is preventDefault'd by the parent Card wrapper
          // when the widget itself has a deep_link, but quick_actions
          // intentionally has no widget-level deep_link, so this Link
          // is the only navigation target.
          return (
            <Link
              key={a.id ?? i}
              to={a.deep_link}
              onClick={(e) => e.stopPropagation()}
              className={cls}
            >
              {inner}
            </Link>
          );
        }
        return (
          <button key={a.id ?? i} type="button" className={cls}>
            {inner}
          </button>
        );
      })}
    </div>
  );
}

function NowPlayingView({ body }: { body: Record<string, unknown> }) {
  const playing = body.playing as boolean | undefined;
  const title = String(body.title ?? '');
  const station = body.station ? String(body.station) : null;
  if (!playing) {
    return <p className="text-sm text-fg-muted">In silenzio.</p>;
  }
  return (
    <div className="flex items-center gap-3">
      <span className="h-9 w-9 rounded-pill bg-accent/15 text-accent flex items-center justify-center animate-breathe">
        <Icon name="radio" size={18} />
      </span>
      <div className="min-w-0">
        <div className="text-sm font-medium truncate">{title || 'In riproduzione'}</div>
        {station && <div className="text-2xs text-fg-muted truncate">{station}</div>}
      </div>
    </div>
  );
}

// Map WMO icon slugs from cara/services/weather.py → emoji glyph.
// Falls back to a clean placeholder when the slug is unknown.
const WEATHER_EMOJI: Record<string, string> = {
  'sun': '☀️',
  'sun-cloud': '🌤️',
  'cloud-sun': '⛅',
  'cloud': '☁️',
  'fog': '🌫️',
  'drizzle': '🌦️',
  'rain': '🌧️',
  'rain-heavy': '🌧️',
  'showers': '🌦️',
  'snow': '❄️',
  'snow-heavy': '🌨️',
  'snow-showers': '🌨️',
  'thunderstorm': '⛈️',
  'thunderstorm-hail': '🌩️',
};

function WeatherView({ body }: { body: Record<string, unknown> }) {
  const available = body.available as boolean | undefined;
  if (available === false) {
    const reason = String(
      body.reason ?? 'Imposta la città in /admin (Impostazioni → Residenza).',
    );
    return <p className="text-sm text-fg-muted">{reason}</p>;
  }
  // Backend (cara.widgets.catalog.WeatherNowWidget) sends:
  //   temperature_c, apparent_temperature_c, label, icon_slug, is_day, location
  const tempVal = body.temperature_c as number | undefined;
  const apparent = body.apparent_temperature_c as number | undefined;
  const label = String(body.label ?? '');
  const slug = String(body.icon_slug ?? '');
  const isDay = body.is_day !== false;
  const emoji = WEATHER_EMOJI[slug]
    ?? (isDay ? WEATHER_EMOJI['sun'] : '🌙');
  const temp = tempVal != null ? `${Math.round(tempVal)}°` : '—';
  return (
    <div className="flex items-center gap-4">
      <span className="text-5xl leading-none select-none" aria-hidden>
        {emoji}
      </span>
      <div className="min-w-0">
        <div className="font-display text-3xl text-fg leading-none">{temp}</div>
        {label && (
          <div className="text-sm text-fg-soft mt-1 capitalize">{label}</div>
        )}
        {apparent != null && (
          <div className="text-2xs text-fg-muted mt-0.5">
            percepiti {Math.round(apparent)}°
          </div>
        )}
      </div>
    </div>
  );
}

function QuoteView({ body }: { body: Record<string, unknown> }) {
  const text = String(body.text ?? body.quote ?? '');
  const author = body.author ? String(body.author) : null;
  return (
    <div>
      <p className="text-sm text-fg italic leading-relaxed">"{text}"</p>
      {author && (
        <p className="text-xs text-fg-muted mt-2 text-right">— {author}</p>
      )}
    </div>
  );
}

const CATEGORY_LABEL: Record<string, string> = {
  legumi: 'Legumi', pesce: 'Pesce', carne: 'Carne', uova: 'Uova', formaggio: 'Formaggio',
};

interface DietCategory {
  category: string;
  color: string;
  consumed: number;
  target_min: number | null;
  target_max: number | null;
  state: string; // ok | under | over | warn
}

function DietSummaryView({ body }: { body: Record<string, unknown> }) {
  if (body.available === false) {
    return (
      <p className="text-sm text-fg-muted">
        Compila il profilo nutrizionale per vedere il resoconto.
      </p>
    );
  }

  const target = body.daily_target as number | null;
  const consumed = (body.consumed as number) ?? 0;
  const burned = (body.burned as number) ?? 0;
  const remaining = body.remaining as number | null;
  const adherence = (body.adherence_score as number) ?? 0;
  const avgKcal = body.avg_kcal_per_day as number | null;
  const water = (body.water_ml as number) ?? 0;
  const categories = (body.categories as DietCategory[] | undefined) ?? [];
  const profileComplete = body.profile_complete !== false;

  // Progress of the day's intake vs target (0..1, clamped).
  const pct =
    target && target > 0 ? Math.min(1, consumed / target) : 0;
  const remainingTone =
    remaining != null && remaining < 0 ? 'text-alert' : 'text-violet-600 dark:text-violet-300';

  const STATE_DOT: Record<string, string> = {
    ok: 'bg-ok', under: 'bg-amber-400', over: 'bg-alert', warn: 'bg-amber-500',
  };

  return (
    <div className="space-y-3">
      {/* Energy balance */}
      {profileComplete ? (
        <div>
          <div className="flex items-baseline justify-between">
            <span className="font-display text-2xl text-fg leading-none">
              {consumed}<span className="text-sm text-fg-muted"> kcal</span>
            </span>
            {target != null && (
              <span className="text-2xs text-fg-muted">obiettivo {target}</span>
            )}
          </div>
          <div className="h-1.5 rounded-full bg-surface2 overflow-hidden mt-1.5">
            <div
              className={cn('h-full', pct >= 1 ? 'bg-alert' : 'bg-accent')}
              style={{ width: `${Math.round(pct * 100)}%` }}
            />
          </div>
          <div className="grid grid-cols-3 gap-2 mt-2 text-center">
            <MiniStat label="bruciate" value={`−${burned}`} tone="text-emerald-600 dark:text-emerald-300" />
            <MiniStat label="residue" value={remaining != null ? String(remaining) : '—'} tone={remainingTone} />
            <MiniStat label="media/gg" value={avgKcal != null ? String(avgKcal) : '—'} tone="text-sky-600 dark:text-sky-300" />
          </div>
        </div>
      ) : (
        <p className="text-sm text-fg-muted">Profilo incompleto — calorie non stimabili.</p>
      )}

      {/* Weekly adherence */}
      <div className="pt-2 border-t border-fg/8">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-2xs text-fg-muted uppercase tracking-wide">Aderenza settimana</span>
          <span className={cn(
            'text-sm font-semibold',
            adherence >= 80 ? 'text-ok' : adherence >= 60 ? 'text-amber-600' : 'text-alert',
          )}>
            {Math.round(adherence)}%
          </span>
        </div>
        {categories.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {categories.map((c) => (
              <span
                key={c.category}
                className="inline-flex items-center gap-1 rounded-pill bg-surface2 px-2 py-0.5 text-2xs text-fg"
                title={`${CATEGORY_LABEL[c.category] ?? c.category}: ${c.consumed}${
                  c.target_max != null ? `/${c.target_max}` : ''
                }`}
              >
                <span className={cn('h-1.5 w-1.5 rounded-full', STATE_DOT[c.state] ?? 'bg-fg/30')} />
                {CATEGORY_LABEL[c.category] ?? c.category} {c.consumed}
                {c.target_max != null ? `/${c.target_max}` : ''}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Hydration */}
      <div className="flex items-center gap-1.5 text-2xs text-fg-muted pt-1">
        <span>💧 {(water / 1000).toFixed(1)}L oggi</span>
      </div>
    </div>
  );
}

function MiniStat({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div>
      <div className={cn('text-base font-bold leading-none', tone)}>{value}</div>
      <div className="text-2xs text-fg-muted mt-0.5">{label}</div>
    </div>
  );
}

function FallbackView({ body }: { body: Record<string, unknown> }) {
  const keys = Object.keys(body);
  if (keys.length === 0) {
    return <p className="text-sm text-fg-muted">Niente da mostrare.</p>;
  }
  return (
    <ul className="space-y-1">
      {keys.slice(0, 4).map(k => {
        const v = body[k];
        const display = typeof v === 'object' ? '…' : String(v);
        return (
          <li key={k} className="text-xs text-fg-soft">
            <span className="text-fg-muted capitalize">{k.replace(/_/g, ' ')}:</span>{' '}
            <span className="text-fg">{display}</span>
          </li>
        );
      })}
    </ul>
  );
}

// ── Helpers ───────────────────────────────────────────────────

function formatDue(unix?: number | null): string | undefined {
  if (!unix) return undefined;
  const ms = unix * 1000;
  const now = Date.now();
  const diff = ms - now;
  const dayMs = 24 * 60 * 60 * 1000;
  if (diff < -dayMs) return 'in ritardo';
  if (diff < 0)      return 'oggi';
  if (diff < dayMs)  return 'oggi';
  if (diff < 2 * dayMs) return 'domani';
  if (diff < 7 * dayMs) return `${Math.round(diff / dayMs)}g`;
  const d = new Date(ms);
  return `${d.getDate()}/${d.getMonth() + 1}`;
}
