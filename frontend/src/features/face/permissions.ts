/**
 * Client-side smart-home permission gate.
 *
 * The full authority lives on the backend (Home Assistant + CARA's
 * smart-home adapter enforce permissions server-side regardless of who
 * the client thinks is active). This module is a *first-line* filter
 * that hides dangerous actions from the UI when the active profile is
 * a child — so the affordance never appears, and the user is never
 * left wondering why a button is greyed out.
 *
 * If you add a sensitive integration (e.g. a smart oven), add its
 * action signature to `CHILD_BLOCKED_ACTIONS`.
 */

import { useActiveProfile, type ActiveProfile } from './ActiveProfileContext';


/**
 * Dangerous smart-home action signatures. Matching is substring-based
 * so "lock.unlock" matches "lock.unlock_front_door" etc.
 */
const CHILD_BLOCKED_ACTIONS = [
  'lock.unlock',
  'lock.open',
  'cover.open',          // garage doors fall under HA cover.* domain
  'climate.set_temperature',
  'switch.gas',
  'switch.boiler',
  'switch.oven',
  'switch.iron',
  'media_player.volume_set', // volume jumps can scare a child / hurt ears
  'alarm_control_panel',
  'phone.call',
  'phone.dial',
] as const;


export interface PermissionCheck {
  allowed: boolean;
  reason: string | null;
}


/** Default-allow when there's no active profile (adult presumed). */
export function canPerformAction(
  action: string,
  active: ActiveProfile | null,
): PermissionCheck {
  if (!active || !active.isChild) return { allowed: true, reason: null };

  const blocked = CHILD_BLOCKED_ACTIONS.some((sig) => action.includes(sig));
  if (blocked) {
    return {
      allowed: false,
      reason: `Azione non disponibile in modalità bambino (utente attivo: ${active.displayName}).`,
    };
  }
  return { allowed: true, reason: null };
}


/**
 * Sugar for React components: returns the disabled flag + tooltip text.
 *
 *   const { disabled, tooltip } = useChildSafe('lock.unlock')
 *   <button disabled={disabled} title={tooltip ?? undefined}>...
 */
export function useChildSafe(action: string): { disabled: boolean; tooltip: string | null } {
  const { active } = useActiveProfile();
  const { allowed, reason } = canPerformAction(action, active);
  return { disabled: !allowed, tooltip: allowed ? null : reason };
}
