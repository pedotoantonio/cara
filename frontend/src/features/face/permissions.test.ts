/**
 * Unit tests for the smart-home permission gate.
 *
 * The hook `useChildSafe` needs a React provider so it's not covered
 * here. The pure helper `canPerformAction` is tested directly with a
 * synthetic ActiveProfile.
 */

import { describe, expect, it } from 'vitest';

import type { ActiveProfile } from './ActiveProfileContext';

import { canPerformAction } from './permissions';


function profile(isChild: boolean): ActiveProfile {
  return {
    profileId: 'test-id',
    displayName: 'Test',
    isChild,
    companions: [],
    identifiedAt: 0,
  };
}


describe('canPerformAction', () => {
  it('allows everything when no profile is active', () => {
    expect(canPerformAction('lock.unlock_front', null).allowed).toBe(true);
    expect(canPerformAction('switch.gas_valve', null).allowed).toBe(true);
  });

  it('allows everything for an adult profile', () => {
    const adult = profile(false);
    expect(canPerformAction('lock.unlock_front', adult).allowed).toBe(true);
    expect(canPerformAction('switch.oven', adult).allowed).toBe(true);
  });

  it('blocks dangerous actions for a child profile', () => {
    const child = profile(true);
    for (const action of [
      'lock.unlock_garage',
      'switch.gas_main',
      'switch.boiler_heating',
      'switch.oven_top',
      'climate.set_temperature_living',
      'phone.call_emergency',
      'alarm_control_panel.disarm',
    ]) {
      const r = canPerformAction(action, child);
      expect(r.allowed, action).toBe(false);
      expect(r.reason, action).toMatch(/modalità bambino/i);
    }
  });

  it('lets safe actions through for a child profile', () => {
    const child = profile(true);
    for (const action of [
      'light.turn_on_kitchen',
      'media_player.play_radio',
      'sensor.read_temperature',
      'climate.read_state',
    ]) {
      expect(canPerformAction(action, child).allowed, action).toBe(true);
    }
  });
});
