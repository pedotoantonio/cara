/**
 * Visual indicator: "Stai parlando con <nome>" + companions count.
 *
 * Drop this anywhere in an admin/surface header. It is fully passive:
 * does NOT start the worker, doesn't open the camera; it just reads
 * the ActiveProfileContext.
 *
 * Renders nothing when no profile is active so it's safe to mount
 * unconditionally.
 */

import { useActiveProfile } from '../ActiveProfileContext';


export function ActiveProfileBadge() {
  const { active, childMode } = useActiveProfile();
  if (!active) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className={
        childMode
          ? 'inline-flex items-center gap-2 rounded-full bg-rose-100 text-rose-900 px-3 py-1 text-xs font-medium'
          : 'inline-flex items-center gap-2 rounded-full bg-emerald-100 text-emerald-900 px-3 py-1 text-xs font-medium'
      }
      title={
        active.companions.length > 0
          ? `Con: ${active.companions.map((c) => c.displayName).join(', ')}`
          : undefined
      }
    >
      <span className="relative inline-flex h-2 w-2">
        <span
          className={
            childMode
              ? 'absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-60'
              : 'absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60'
          }
        />
        <span
          className={
            childMode
              ? 'relative inline-flex h-2 w-2 rounded-full bg-rose-500'
              : 'relative inline-flex h-2 w-2 rounded-full bg-emerald-500'
          }
        />
      </span>
      <span>
        Ciao <strong>{active.displayName}</strong>
        {childMode && <span aria-hidden> 🧸</span>}
      </span>
      {active.companions.length > 0 && (
        <span className="opacity-75">
          + {active.companions.length}
        </span>
      )}
    </div>
  );
}
