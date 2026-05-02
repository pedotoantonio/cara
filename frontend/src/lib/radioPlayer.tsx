/**
 * Global radio player.
 *
 * Single hidden <audio> element that lives at app root; any component can
 * call `playStation(station)` / `stop()` / read `current`. Avoids spawning
 * multiple audio elements when navigating between pages.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import type { RadioStation } from '../api/radio';

interface RadioPlayerApi {
  current: RadioStation | null;
  playing: boolean;
  volume: number;
  playStation: (s: RadioStation) => void;
  stop: () => void;
  setVolume: (v: number) => void;
}

const Ctx = createContext<RadioPlayerApi | null>(null);

export function RadioPlayerProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [current, setCurrent] = useState<RadioStation | null>(null);
  const [playing, setPlaying] = useState(false);
  const [volume, setVolumeState] = useState(0.6);

  // Spawn audio element once.
  useEffect(() => {
    const a = new Audio();
    a.preload = 'none';
    a.crossOrigin = 'anonymous'; // best-effort; ignored if origin doesn't allow
    a.volume = volume;
    audioRef.current = a;
    a.onplaying = () => setPlaying(true);
    a.onpause = () => setPlaying(false);
    a.onerror = () => setPlaying(false);
    return () => {
      a.pause();
      a.src = '';
      audioRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = volume;
  }, [volume]);

  const playStation = useCallback((s: RadioStation) => {
    const a = audioRef.current;
    if (!a) return;
    if (current?.id !== s.id) {
      a.src = s.url;
    }
    setCurrent(s);
    a.play().catch((err) => {
      // Most browsers block .play() outside a user gesture. Surface state.
      console.warn('radio.play_blocked', err);
      setPlaying(false);
    });
  }, [current]);

  const stop = useCallback(() => {
    const a = audioRef.current;
    if (!a) return;
    a.pause();
    a.src = '';
    setCurrent(null);
    setPlaying(false);
  }, []);

  const setVolume = useCallback((v: number) => {
    setVolumeState(Math.max(0, Math.min(1, v)));
  }, []);

  return (
    <Ctx.Provider value={{ current, playing, volume, playStation, stop, setVolume }}>
      {children}
    </Ctx.Provider>
  );
}

export function useRadioPlayer(): RadioPlayerApi {
  const c = useContext(Ctx);
  if (!c) {
    return {
      current: null,
      playing: false,
      volume: 0,
      playStation: () => undefined,
      stop: () => undefined,
      setVolume: () => undefined,
    };
  }
  return c;
}
