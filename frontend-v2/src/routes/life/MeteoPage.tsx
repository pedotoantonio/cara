import { useQuery } from '@tanstack/react-query';
import { Sun, CloudRain, Cloud, Snowflake, Lightning } from '@phosphor-icons/react';
import { Card, CardSubtitle, Skeleton } from '@/design/components';
import { fetchFamilyResidence, fetchWeather } from '@/api/home';
import { fetchForecast } from '@/api/weather';
import { cn } from '@/lib/cn';

function iconFor(slug: string) {
  if (slug.includes('rain') || slug.includes('drizzle')) return CloudRain;
  if (slug.includes('snow')) return Snowflake;
  if (slug.includes('thunder') || slug.includes('storm')) return Lightning;
  if (slug.includes('cloud') || slug.includes('fog')) return Cloud;
  return Sun;
}

function accentFor(slug: string) {
  if (slug.includes('rain') || slug.includes('drizzle')) return 'text-accent-sky';
  if (slug.includes('snow')) return 'text-accent-sky';
  if (slug.includes('thunder') || slug.includes('storm')) return 'text-accent-lilac';
  if (slug.includes('cloud') || slug.includes('fog')) return 'text-text-secondary';
  return 'text-accent-sun';
}

const WEEKDAYS = ['Dom', 'Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab'];

export function MeteoPage() {
  const residenceQ = useQuery({
    queryKey: ['family.residence'],
    queryFn: fetchFamilyResidence,
    staleTime: 5 * 60_000,
  });

  const currentQ = useQuery({
    queryKey: ['weather.current', residenceQ.data?.lat, residenceQ.data?.lon],
    queryFn: () =>
      residenceQ.data ? fetchWeather(residenceQ.data.lat, residenceQ.data.lon) : null,
    enabled: !!residenceQ.data,
    staleTime: 5 * 60_000,
  });

  const forecastQ = useQuery({
    queryKey: ['weather.forecast', residenceQ.data?.lat, residenceQ.data?.lon],
    queryFn: () =>
      residenceQ.data ? fetchForecast(residenceQ.data.lat, residenceQ.data.lon) : null,
    enabled: !!residenceQ.data,
    staleTime: 30 * 60_000,
  });

  const cur = currentQ.data;
  const Icon = cur ? iconFor(cur.icon_slug) : Sun;

  return (
    <div className="container-app py-4 space-y-4">
      {currentQ.isLoading && <Skeleton className="h-48 w-full" />}

      {cur && (
        <Card padding="lg" elevation={2}>
          <div className="flex items-center gap-4">
            <Icon size={72} weight="duotone" className={accentFor(cur.icon_slug)} />
            <div className="flex-1">
              <p className="text-text-secondary text-sm">{cur.city}</p>
              <p className="font-display text-5xl text-text-primary">
                {cur.temperature != null ? Math.round(cur.temperature) + '°' : '—'}
              </p>
              <p className="text-md text-text-primary mt-1">{cur.label}</p>
              {cur.apparent != null && (
                <p className="text-xs text-text-muted">
                  percepiti {Math.round(cur.apparent)}°
                </p>
              )}
            </div>
          </div>
        </Card>
      )}

      {forecastQ.data && forecastQ.data.daily.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-2 px-1">
            Prossimi giorni
          </h2>
          <ul className="space-y-2">
            {forecastQ.data.daily.map((d) => {
              const DI = iconFor(d.icon_slug);
              const date = new Date(d.date);
              return (
                <li key={d.date}>
                  <Card padding="base" elevation={1}>
                    <div className="flex items-center gap-4">
                      <div className="w-12 flex-shrink-0">
                        <p className="text-xs font-semibold uppercase text-text-secondary">
                          {WEEKDAYS[date.getDay()]}
                        </p>
                        <p className="text-xs text-text-muted">{date.getDate()}</p>
                      </div>
                      <DI size={32} weight="duotone" className={cn('flex-shrink-0', accentFor(d.icon_slug))} />
                      <p className="flex-1 text-sm text-text-secondary truncate">{d.label}</p>
                      <div className="text-right">
                        <p className="font-medium text-text-primary">
                          {Math.round(d.temperature_max)}°
                          <span className="text-text-muted ml-1 text-sm">
                            {Math.round(d.temperature_min)}°
                          </span>
                        </p>
                        {d.precipitation_mm > 0 && (
                          <CardSubtitle>{d.precipitation_mm.toFixed(1)} mm</CardSubtitle>
                        )}
                      </div>
                    </div>
                  </Card>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {!forecastQ.isLoading && !forecastQ.data && (
        <p className="text-text-muted text-sm text-center py-4">
          Previsioni non disponibili.
        </p>
      )}
    </div>
  );
}
