// CaraFace block for the Wall header — avatar + 1-line caption that
// reacts to family-bus events (presence, proactivity, tts).

import { CaraFace } from '../CaraFace';
import { useWallEventStream } from '../../hooks/useWallEventStream';

export function WallAvatarPanel({ size = 140 }: { size?: number }) {
  const { mood, online } = useWallEventStream();

  return (
    <div className="flex flex-col items-center justify-center gap-2 select-none">
      <div style={{ width: size, height: size }}>
        <CaraFace energy={mood.energy} emotion={mood.emotion} size={size} />
      </div>
      <div className="text-center min-h-[24px]">
        {mood.caption ? (
          <span
            className="text-fg-soft animate-breathe"
            style={{ fontSize: 'clamp(14px, 1.2vw, 18px)' }}
          >
            {mood.caption}
          </span>
        ) : (
          <span
            className="text-fg-muted"
            style={{ fontSize: 'clamp(14px, 1.2vw, 18px)' }}
          >
            CARA è qui
          </span>
        )}
      </div>
      {!online && (
        <span
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted"
          title="Connessione al backend in corso…"
        >
          <span
            className="inline-block w-2 h-2 rounded-full bg-alert animate-pulse"
          />
          offline
        </span>
      )}
    </div>
  );
}
