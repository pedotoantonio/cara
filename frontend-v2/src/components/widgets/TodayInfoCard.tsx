// TodayInfoCard — widget che mostra le info del giorno (santo, fase
// lunare, alba/tramonto, proverbio, countdown prossimi eventi).
//
// Usato sia in Hub Casa (compatto) sia in /life/calendar (esteso).

import { useQuery } from '@tanstack/react-query';
import { Sun, Moon, CalendarStar } from '@phosphor-icons/react';
import { Skeleton } from '@/design/components';
import { getDayInfo, type DayInfo } from '@/api/calendarInfo';

interface Props {
  variant?: 'compact' | 'full';
  dateIso?: string;
}

export function TodayInfoCard({ variant = 'compact', dateIso }: Props) {
  const q = useQuery({
    queryKey: ['calendar', 'day-info', dateIso ?? 'today'],
    queryFn: () => getDayInfo(dateIso),
    staleTime: 60 * 60_000, // 1h
  });

  if (q.isLoading) return <Skeleton className="h-32" />;
  if (q.isError || !q.data) {
    return (
      <div className="p-4 text-sm text-text-muted">
        Info giornaliere non disponibili.
      </div>
    );
  }

  return variant === 'compact' ? (
    <CompactCard info={q.data} />
  ) : (
    <FullCard info={q.data} />
  );
}

function CompactCard({ info }: { info: DayInfo }) {
  return (
    <div className="p-4 rounded-xl bg-bg-elevated border border-border-soft space-y-2">
      <header className="flex items-center justify-between">
        <h3 className="font-display text-lg text-text-primary capitalize">
          {info.long_format_it}
        </h3>
        <span className="text-xs text-text-muted">Settimana {info.week_number}</span>
      </header>

      {info.is_holiday && info.holiday_name && (
        <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-accent-coral/10 text-accent-coral text-sm">
          🎉 <strong>{info.holiday_name}</strong>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 text-sm">
        {info.saint && (
          <div className="flex items-start gap-2">
            <CalendarStar size={16} className="text-accent-sun mt-0.5 flex-shrink-0" />
            <span className="text-text-secondary">{info.saint}</span>
          </div>
        )}
        {info.sunrise && info.sunset && (
          <div className="flex items-center gap-2">
            <Sun size={16} className="text-accent-sun" />
            <span className="text-text-secondary text-xs">
              {info.sunrise} → {info.sunset}
            </span>
          </div>
        )}
        <div className="flex items-center gap-2">
          <span className="text-lg">{info.moon_phase_emoji}</span>
          <span className="text-text-secondary text-xs capitalize">
            {info.moon_phase}
          </span>
        </div>
        <div className="text-text-muted text-xs capitalize">
          🌳 {info.season}
        </div>
      </div>

      {info.proverb && (
        <p className="text-xs italic text-text-muted border-l-2 border-border-soft pl-2">
          "{info.proverb}"
        </p>
      )}
    </div>
  );
}

function FullCard({ info }: { info: DayInfo }) {
  return (
    <div className="space-y-4">
      <div className="p-5 rounded-2xl bg-bg-elevated border border-border-soft">
        <h2 className="font-display text-2xl text-text-primary capitalize mb-1">
          {info.long_format_it}
        </h2>
        <p className="text-sm text-text-muted">
          Settimana {info.week_number} · {info.season}
        </p>

        {info.is_holiday && info.holiday_name && (
          <div className="mt-3 px-3 py-2 rounded-lg bg-accent-coral/10 text-accent-coral">
            🎉 Oggi è <strong>{info.holiday_name}</strong>
          </div>
        )}

        {info.notes.length > 0 && (
          <ul className="mt-3 space-y-1 text-sm text-text-secondary">
            {info.notes.map((n, i) => (
              <li key={i}>• {n}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {info.saint && (
          <InfoTile
            icon={<CalendarStar size={20} className="text-accent-sun" />}
            label="Santo del giorno"
            value={info.saint}
          />
        )}
        {info.sunrise && info.sunset && info.daylight_hours && (
          <InfoTile
            icon={<Sun size={20} className="text-accent-sun" />}
            label="Sole"
            value={`${info.sunrise} → ${info.sunset}`}
            sub={`${info.daylight_hours.toFixed(1)}h di luce`}
          />
        )}
        <InfoTile
          icon={<Moon size={20} />}
          label={`Luna ${info.moon_phase}`}
          value={`${info.moon_phase_emoji} ${Math.round(info.moon_illumination * 100)}% illuminata`}
        />
        <InfoTile
          icon={<span className="text-xl">🌳</span>}
          label="Stagione"
          value={info.season}
          capitalize
        />
      </div>

      {info.proverb && (
        <div className="p-4 rounded-xl bg-accent-mint/8 border border-accent-mint/30">
          <p className="text-xs text-text-muted mb-1">Proverbio del mese</p>
          <p className="text-base italic text-text-primary">"{info.proverb}"</p>
        </div>
      )}

      {info.countdowns.length > 0 && (
        <div className="p-4 rounded-xl bg-bg-elevated border border-border-soft">
          <h3 className="font-display text-lg text-text-primary mb-2">
            Prossimi eventi
          </h3>
          <ul className="space-y-2">
            {info.countdowns.map((c) => (
              <li
                key={c.date}
                className="flex items-center justify-between text-sm"
              >
                <span>
                  {c.emoji} <strong>{c.label}</strong>
                </span>
                <span className="text-text-muted">
                  {c.days_to === 0
                    ? 'oggi'
                    : c.days_to === 1
                      ? 'domani'
                      : `fra ${c.days_to} giorni`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function InfoTile({
  icon,
  label,
  value,
  sub,
  capitalize,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  capitalize?: boolean;
}) {
  return (
    <div className="p-3 rounded-xl bg-bg-elevated border border-border-soft">
      <div className="flex items-center gap-2 text-xs text-text-muted mb-1">
        {icon}
        <span>{label}</span>
      </div>
      <p className={`text-sm text-text-primary ${capitalize ? 'capitalize' : ''}`}>
        {value}
      </p>
      {sub && <p className="text-xs text-text-muted mt-0.5">{sub}</p>}
    </div>
  );
}
