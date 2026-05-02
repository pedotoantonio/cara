/**
 * Persistent mini bar shown above the bottom nav whenever a radio station
 * is loaded. Tap stop to silence; volume slider for quick adjust.
 */

import { useRadioPlayer } from '../lib/radioPlayer';

export function RadioMiniBar() {
  const player = useRadioPlayer();
  if (!player.current) return null;
  return (
    <div className="border-t border-slate-800 bg-slate-900/95 px-3 py-2 flex items-center gap-3">
      <span className="text-lg">📻</span>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium truncate">
          {player.current.name}
          {player.playing ? '' : ' (in pausa)'}
        </p>
      </div>
      <input
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={player.volume}
        onChange={(e) => player.setVolume(Number(e.target.value))}
        className="w-16 sm:w-24 accent-emerald-500"
        aria-label="volume radio"
      />
      <button
        type="button"
        onClick={() => (player.playing ? player.stop() : player.playStation(player.current!))}
        className="text-slate-300 hover:text-white text-base"
        aria-label={player.playing ? 'stop' : 'play'}
      >
        {player.playing ? '⏹' : '▶'}
      </button>
    </div>
  );
}
