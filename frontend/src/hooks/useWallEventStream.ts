// SSE-driven avatar / caption state for the Wall surface. Subscribes
// to `/api/v1/wall/events/stream` (no auth — Wall is LAN-public) and
// maps whitelisted family-bus events into a (emotion, energy, caption)
// triple consumed by `WallAvatarPanel`.
//
// Reconnect with exp backoff (2s → 4s → … → 60s). The event stream is
// "best effort"; if it disconnects the Wall keeps showing the last
// known mood until the connection comes back.

import { useEffect, useRef, useState } from 'react';

import { WALL_EVENTS_URL } from '../api/wall';
import type { Emotion, EnergyState } from '../components/CaraFace';

export interface AvatarMood {
  emotion: Emotion;
  energy: EnergyState;
  caption: string;
  /** Unix ms after which the mood decays to calm/idle. 0 = no decay. */
  expiresAt: number;
}

const DEFAULT_MOOD: AvatarMood = {
  emotion: 'neutral',
  energy: 'idle',
  caption: '',
  expiresAt: 0,
};

interface BusEvent {
  kind: string;
  payload: Record<string, unknown>;
}

/** Map a family-bus event to an avatar mood + how long it lingers. */
function moodFor(ev: BusEvent): AvatarMood | null {
  const k = ev.kind;
  const p = ev.payload || {};
  const name = (p.name as string) || '';

  if (k === 'presence.known.arrived') {
    return {
      emotion: 'happy',
      energy: 'idle',
      caption: name ? `${name} è appena arrivato` : 'Qualcuno è arrivato',
      expiresAt: Date.now() + 15_000,
    };
  }
  if (k === 'presence.unknown.detected') {
    return {
      emotion: 'surprised',
      energy: 'sensing',
      caption: 'Qualcuno è alla porta',
      expiresAt: Date.now() + 20_000,
    };
  }
  if (k === 'tts.speaking.start') {
    return {
      emotion: 'neutral',
      energy: 'speaking',
      caption: 'Sto parlando…',
      expiresAt: Date.now() + 8_000,
    };
  }
  if (k === 'tts.speaking.end') {
    return { ...DEFAULT_MOOD, expiresAt: Date.now() + 1_000 };
  }
  if (k.startsWith('proactivity.fired')) {
    const rule = (p.rule_id as string) || '';
    let emotion: Emotion = 'thoughtful';
    let caption = 'Promemoria';
    if (rule === 'morning_greeting') {
      emotion = 'happy';
      caption = 'Buongiorno!';
    } else if (rule === 'rain_alert') {
      emotion = 'thoughtful';
      caption = 'Pioggia in arrivo';
    } else if (rule === 'undone_tasks_evening') {
      emotion = 'thoughtful';
      caption = 'Ci sono task da chiudere';
    } else if (rule === 'birthday_today') {
      emotion = 'joyful';
      caption = 'Buon compleanno!';
    } else if (rule === 'bedtime_routine') {
      emotion = 'sleepy';
      caption = 'È quasi ora di dormire';
    }
    return { emotion, energy: 'idle', caption, expiresAt: Date.now() + 20_000 };
  }
  if (k === 'task.due_soon') {
    const cnt = Number(p.count || 1);
    return {
      emotion: 'thoughtful',
      energy: 'idle',
      caption: `${cnt} task in scadenza`,
      expiresAt: Date.now() + 15_000,
    };
  }
  return null;
}

export function useWallEventStream(): {
  mood: AvatarMood;
  online: boolean;
} {
  const [mood, setMood] = useState<AvatarMood>(DEFAULT_MOOD);
  const [online, setOnline] = useState<boolean>(false);
  const sourceRef = useRef<EventSource | null>(null);
  const decayTimerRef = useRef<number | null>(null);
  const backoffRef = useRef<number>(2000);

  useEffect(() => {
    let cancelled = false;

    function scheduleDecay(at: number) {
      if (decayTimerRef.current) {
        window.clearTimeout(decayTimerRef.current);
      }
      const ms = Math.max(0, at - Date.now());
      if (ms === 0) return;
      decayTimerRef.current = window.setTimeout(() => {
        setMood(DEFAULT_MOOD);
      }, ms);
    }

    function connect() {
      if (cancelled) return;
      try {
        const es = new EventSource(WALL_EVENTS_URL);
        sourceRef.current = es;

        es.addEventListener('open', () => {
          if (cancelled) return;
          setOnline(true);
          backoffRef.current = 2000;
        });

        // Generic handler — every server-sent event carries
        // `event: <kind>\ndata: <json>` so we listen on `message`
        // (default) only as fallback; named handlers below catch
        // typed events.
        const onAny = (e: MessageEvent) => {
          let parsed: BusEvent | null = null;
          try {
            parsed = JSON.parse(e.data) as BusEvent;
          } catch {
            return;
          }
          if (!parsed || !parsed.kind) return;
          const next = moodFor(parsed);
          if (!next) return;
          setMood(next);
          if (next.expiresAt > 0) scheduleDecay(next.expiresAt);
        };

        // Wildcard via individual listeners — EventSource doesn't have
        // a wildcard, so we register a small set of known kinds.
        const KNOWN_KINDS = [
          'presence.known.arrived',
          'presence.unknown.detected',
          'tts.speaking.start',
          'tts.speaking.end',
          'proactivity.fired',
          'task.due_soon',
        ];
        for (const k of KNOWN_KINDS) {
          es.addEventListener(k, onAny as EventListener);
        }
        es.addEventListener('message', onAny as EventListener);

        es.addEventListener('error', () => {
          if (cancelled) return;
          setOnline(false);
          es.close();
          sourceRef.current = null;
          // Reconnect with exp backoff capped at 60s.
          const delay = backoffRef.current;
          backoffRef.current = Math.min(delay * 2, 60_000);
          window.setTimeout(connect, delay);
        });
      } catch {
        if (cancelled) return;
        setOnline(false);
        const delay = backoffRef.current;
        backoffRef.current = Math.min(delay * 2, 60_000);
        window.setTimeout(connect, delay);
      }
    }

    connect();

    return () => {
      cancelled = true;
      if (decayTimerRef.current) window.clearTimeout(decayTimerRef.current);
      if (sourceRef.current) sourceRef.current.close();
      sourceRef.current = null;
    };
  }, []);

  return { mood, online };
}
