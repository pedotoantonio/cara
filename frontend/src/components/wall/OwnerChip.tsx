// OwnerChip — visual identity of a family member on the Wall. Two
// sizes: compact (24px circle with emoji) and full (pill with emoji +
// name). Color comes from `user.color` (hex). Falls back to grey when
// owner is null (= shared / family-level item).

import type { WallUser } from '../../api/wall';

interface OwnerChipProps {
  user: WallUser | null;
  variant?: 'dot' | 'compact' | 'full';
  className?: string;
}

function readableTextColor(bgHex: string): string {
  // Quick luminance heuristic: dark bg → white text, light bg → near-black.
  const m = bgHex.match(/^#?([0-9a-f]{6})$/i);
  if (!m) return '#0f172a';
  const v = parseInt(m[1], 16);
  const r = (v >> 16) & 0xff;
  const g = (v >> 8) & 0xff;
  const b = v & 0xff;
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.6 ? '#0f172a' : '#ffffff';
}

export function OwnerChip({ user, variant = 'compact', className = '' }: OwnerChipProps) {
  if (variant === 'dot') {
    const color = user?.color ?? '#94a3b8';
    return (
      <span
        className={`inline-block rounded-full ${className}`}
        style={{ width: 12, height: 12, background: color }}
        title={user?.display_name ?? 'Famiglia'}
      />
    );
  }

  if (!user) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-full bg-surface2 text-fg-muted ${className}`}
        style={{
          padding: variant === 'compact' ? '2px 8px' : '4px 10px',
          fontSize: variant === 'compact' ? 12 : 14,
        }}
      >
        <span className="opacity-60">👨‍👩‍👧</span>
        <span>Famiglia</span>
      </span>
    );
  }

  const bg = user.color;
  const fg = readableTextColor(bg);

  if (variant === 'compact') {
    return (
      <span
        className={`inline-flex items-center justify-center rounded-full font-medium ${className}`}
        style={{
          background: bg,
          color: fg,
          width: 28,
          height: 28,
          fontSize: 14,
        }}
        title={user.display_name}
      >
        {user.emoji}
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium ${className}`}
      style={{
        background: bg,
        color: fg,
        padding: '4px 12px',
        fontSize: 14,
      }}
    >
      <span>{user.emoji}</span>
      <span>{user.display_name}</span>
    </span>
  );
}

export function OwnerStack({
  owners,
  max = 3,
}: {
  owners: WallUser[];
  max?: number;
}) {
  const visible = owners.slice(0, max);
  const overflow = owners.length - visible.length;
  return (
    <span className="inline-flex items-center -space-x-2">
      {visible.map((u) => (
        <OwnerChip key={u.id} user={u} variant="compact" className="ring-2 ring-bg" />
      ))}
      {overflow > 0 && (
        <span className="ml-3 text-xs text-fg-muted">+{overflow}</span>
      )}
    </span>
  );
}
