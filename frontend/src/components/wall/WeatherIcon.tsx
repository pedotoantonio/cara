// Hand-rolled weather icons. We don't pull in lucide/heroicons because
// the CARA design system already exposes a small icon set; weather is
// the one missing family, so we ship just what we need.
//
// Each icon is a self-contained SVG sized via the `size` prop. Stroke
// uses `currentColor`, fills use named hues so day vs night themes
// don't make the sun look black.

interface IconProps {
  size?: number;
  className?: string;
}

export type WeatherSlug =
  | 'clear'
  | 'mostly-clear'
  | 'partly-cloudy'
  | 'cloudy'
  | 'overcast'
  | 'fog'
  | 'drizzle'
  | 'rain'
  | 'rain-heavy'
  | 'rain-showers'
  | 'thunder'
  | 'thunder-heavy'
  | 'snow'
  | 'snow-heavy'
  | 'snow-showers'
  | 'snow-showers-heavy'
  | 'unknown';

function Sun({ size = 48, className = '' }: IconProps) {
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      className={className}
      aria-hidden="true"
    >
      {/* rays */}
      <g stroke="#f59e0b" strokeWidth="3" strokeLinecap="round">
        <line x1="32" y1="6" x2="32" y2="14" />
        <line x1="32" y1="50" x2="32" y2="58" />
        <line x1="6" y1="32" x2="14" y2="32" />
        <line x1="50" y1="32" x2="58" y2="32" />
        <line x1="13" y1="13" x2="19" y2="19" />
        <line x1="45" y1="45" x2="51" y2="51" />
        <line x1="13" y1="51" x2="19" y2="45" />
        <line x1="45" y1="19" x2="51" y2="13" />
      </g>
      <circle cx="32" cy="32" r="12" fill="#fbbf24" stroke="#f59e0b" strokeWidth="2" />
    </svg>
  );
}

function Moon({ size = 48, className = '' }: IconProps) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} aria-hidden="true">
      <path
        d="M44 16a18 18 0 1 0 6 32 14 14 0 0 1-6-32z"
        fill="#e2e8f0"
        stroke="#94a3b8"
        strokeWidth="2"
      />
      <circle cx="38" cy="22" r="1.5" fill="#94a3b8" />
      <circle cx="50" cy="36" r="2" fill="#94a3b8" />
    </svg>
  );
}

function CloudShape({
  fill = '#cbd5e1',
  stroke = '#94a3b8',
}: { fill?: string; stroke?: string }) {
  return (
    <path
      d="M16 42c-5 0-9-4-9-9s4-9 9-9c1 0 2 0 3 .4A12 12 0 0 1 41 28c0-.1.1-.1.1-.1A8 8 0 1 1 47 44H16z"
      fill={fill}
      stroke={stroke}
      strokeWidth="2"
      strokeLinejoin="round"
    />
  );
}

function Cloud({ size = 48, className = '' }: IconProps) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} aria-hidden="true">
      <CloudShape />
    </svg>
  );
}

function PartlyCloudy({ size = 48, className = '', day = true }: IconProps & { day?: boolean }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} aria-hidden="true">
      {day ? (
        <>
          <g stroke="#f59e0b" strokeWidth="2.5" strokeLinecap="round" opacity="0.9">
            <line x1="42" y1="6" x2="42" y2="11" />
            <line x1="58" y1="22" x2="63" y2="22" />
            <line x1="52" y1="10" x2="56" y2="6" />
            <line x1="52" y1="34" x2="56" y2="38" />
          </g>
          <circle cx="44" cy="22" r="9" fill="#fbbf24" stroke="#f59e0b" strokeWidth="2" />
        </>
      ) : (
        <path d="M50 14a10 10 0 1 0 4 18 8 8 0 0 1-4-18z" fill="#e2e8f0" stroke="#94a3b8" strokeWidth="2" />
      )}
      <CloudShape />
    </svg>
  );
}

function RainCloud({ size = 48, className = '', heavy = false }: IconProps & { heavy?: boolean }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} aria-hidden="true">
      <CloudShape fill="#94a3b8" stroke="#64748b" />
      <g stroke="#3b82f6" strokeWidth={heavy ? 3 : 2.5} strokeLinecap="round">
        <line x1="20" y1="48" x2="17" y2="58" />
        <line x1="32" y1="48" x2="29" y2="58" />
        <line x1="44" y1="48" x2="41" y2="58" />
        {heavy && <line x1="26" y1="50" x2="23" y2="60" />}
        {heavy && <line x1="38" y1="50" x2="35" y2="60" />}
      </g>
    </svg>
  );
}

function ThunderCloud({ size = 48, className = '' }: IconProps) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} aria-hidden="true">
      <CloudShape fill="#64748b" stroke="#475569" />
      <path
        d="M30 46 L24 58 L31 58 L28 64 L40 50 L33 50 L36 46 Z"
        fill="#fbbf24"
        stroke="#d97706"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SnowCloud({ size = 48, className = '', heavy = false }: IconProps & { heavy?: boolean }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} aria-hidden="true">
      <CloudShape fill="#e2e8f0" stroke="#94a3b8" />
      <g fill="#cbd5e1" stroke="#94a3b8" strokeWidth="0.8">
        <circle cx="20" cy="52" r={heavy ? 3 : 2.5} />
        <circle cx="32" cy="55" r={heavy ? 3 : 2.5} />
        <circle cx="44" cy="52" r={heavy ? 3 : 2.5} />
        {heavy && <circle cx="26" cy="58" r="2" />}
        {heavy && <circle cx="38" cy="58" r="2" />}
      </g>
    </svg>
  );
}

function Fog({ size = 48, className = '' }: IconProps) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} aria-hidden="true">
      <g stroke="#94a3b8" strokeWidth="3" strokeLinecap="round">
        <line x1="8" y1="20" x2="56" y2="20" />
        <line x1="14" y1="32" x2="50" y2="32" />
        <line x1="6" y1="44" x2="58" y2="44" />
      </g>
    </svg>
  );
}

function Unknown({ size = 48, className = '' }: IconProps) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} aria-hidden="true">
      <circle cx="32" cy="32" r="20" fill="none" stroke="#94a3b8" strokeWidth="2" />
      <text
        x="32"
        y="40"
        textAnchor="middle"
        fontSize="22"
        fontWeight="bold"
        fill="#94a3b8"
      >?</text>
    </svg>
  );
}

export function WeatherIcon({
  slug,
  isDay = true,
  size = 48,
  className = '',
}: {
  slug: string | undefined | null;
  isDay?: boolean;
  size?: number;
  className?: string;
}) {
  // Accept BOTH the backend WMO-derived slugs (sun, sun-cloud,
  // cloud-sun, cloud, drizzle, drizzle-cold, rain, rain-heavy,
  // rain-cold, showers, showers-heavy, snow*, thunderstorm,
  // thunderstorm-hail, fog) AND the original frontend taxonomy
  // (clear, mostly-clear, partly-cloudy, cloudy, overcast, ...).
  // Two callers, one component — must tolerate either.
  const s = (slug ?? 'unknown') as string;
  switch (s) {
    // ─── Clear sky ────────────────────────────────────────────
    case 'sun':
    case 'clear':
      return isDay
        ? <Sun size={size} className={className} />
        : <Moon size={size} className={className} />;

    // ─── Few clouds (sun-with-cloud) ──────────────────────────
    case 'sun-cloud':
    case 'cloud-sun':
    case 'mostly-clear':
    case 'partly-cloudy':
      return <PartlyCloudy size={size} className={className} day={isDay} />;

    // ─── Overcast ─────────────────────────────────────────────
    case 'cloud':
    case 'cloudy':
    case 'overcast':
      return <Cloud size={size} className={className} />;

    // ─── Fog ──────────────────────────────────────────────────
    case 'fog':
      return <Fog size={size} className={className} />;

    // ─── Rain (incl. showers and freezing variants) ───────────
    case 'drizzle':
    case 'drizzle-cold':
    case 'rain':
    case 'rain-cold':
    case 'rain-showers':
    case 'showers':
      return <RainCloud size={size} className={className} />;
    case 'rain-heavy':
    case 'showers-heavy':
      return <RainCloud size={size} className={className} heavy />;

    // ─── Thunder ──────────────────────────────────────────────
    case 'thunder':
    case 'thunderstorm':
    case 'thunderstorm-hail':
      return <ThunderCloud size={size} className={className} />;
    case 'thunder-heavy':
      return <ThunderCloud size={size} className={className} />;

    // ─── Snow ─────────────────────────────────────────────────
    case 'snow':
    case 'snow-showers':
      return <SnowCloud size={size} className={className} />;
    case 'snow-heavy':
    case 'snow-showers-heavy':
      return <SnowCloud size={size} className={className} heavy />;

    default:
      return <Unknown size={size} className={className} />;
  }
}
