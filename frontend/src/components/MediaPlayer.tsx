/**
 * Universal media player.
 *
 * - audio: HTML5 `<audio>` (with HLS.js for `.m3u8`).
 * - video: YouTube embed iframe when `metadata.embed`, else HTML5 `<video>`.
 * - podcast: same as audio.
 * - image: shown as `<img>`.
 * - document (pdf): rendered via iframe.
 *
 * Emits feedback to the CDA on start / stop / error.
 */

import { useEffect, useRef, useState } from 'react';

import { feedbackStarted, feedbackStopped, type CdaKind } from '../api/cda';

interface MediaContent {
  kind: CdaKind;
  url: string;
  title: string | null;
  source_domain: string | null;
  metadata: Record<string, unknown>;
  content_id: string;
}

export function MediaPlayer({
  content,
  onClose,
}: {
  content: MediaContent;
  onClose: () => void;
}) {
  const startedAtRef = useRef<number>(performance.now());
  const reasonRef = useRef<'user_stop' | 'ended' | 'error' | 'switched'>('user_stop');
  const audioRef = useRef<HTMLAudioElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);

  // Mark started right away (the content has been fetched + verified by the
  // server); for HTML5 elements we also re-mark on the first `playing` event.
  useEffect(() => {
    feedbackStarted(content.content_id).catch(() => undefined);
    startedAtRef.current = performance.now();
    reasonRef.current = 'user_stop';
    return () => {
      const playedSeconds = (performance.now() - startedAtRef.current) / 1000;
      feedbackStopped({
        content_id: content.content_id,
        played_seconds: playedSeconds,
        reason: reasonRef.current,
      }).catch(() => undefined);
    };
  }, [content.content_id]);

  // For HLS streams, attach hls.js dynamically.
  useEffect(() => {
    if (content.kind !== 'audio_stream' && content.kind !== 'video') return;
    const isHls = content.url.toLowerCase().includes('.m3u8');
    if (!isHls) return;
    const el = (content.kind === 'audio_stream' ? audioRef.current : videoRef.current) as
      | HTMLMediaElement
      | null;
    if (!el) return;
    if (el.canPlayType('application/vnd.apple.mpegurl')) {
      el.src = content.url;
      return;
    }
    let dispose: (() => void) | null = null;
    (async () => {
      try {
        const Hls = (await import('hls.js')).default;
        if (!Hls.isSupported()) {
          el.src = content.url;
          return;
        }
        const hls = new Hls();
        hls.loadSource(content.url);
        hls.attachMedia(el);
        dispose = () => hls.destroy();
      } catch {
        el.src = content.url;
      }
    })();
    return () => {
      dispose?.();
    };
  }, [content.kind, content.url]);

  function handleEnded() {
    reasonRef.current = 'ended';
    onClose();
  }
  function handleError() {
    reasonRef.current = 'error';
    setError('Riproduzione non riuscita.');
  }

  const youtubeId = (content.metadata?.youtube_id ?? '') as string;
  const isYoutubeEmbed =
    content.kind === 'video' && Boolean(content.metadata?.embed) && youtubeId;

  return (
    <div
      className="fixed inset-x-0 bottom-0 md:bottom-4 md:right-4 md:left-auto md:w-[28rem]
                 z-50 rounded-t-2xl md:rounded-2xl bg-slate-900/95 border border-slate-700
                 shadow-2xl backdrop-blur p-3 space-y-2"
    >
      <div className="flex items-start gap-2">
        <span className="text-xs text-slate-400 mt-0.5">
          {kindLabel(content.kind)}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-100 truncate">{content.title ?? content.url}</p>
          {content.source_domain && (
            <p className="text-[11px] text-slate-500 truncate">
              <a
                href={content.url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-emerald-300"
              >
                {content.source_domain} ↗
              </a>
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => {
            reasonRef.current = 'user_stop';
            onClose();
          }}
          className="text-slate-400 hover:text-slate-100 text-lg leading-none"
          aria-label="Chiudi"
        >
          ✕
        </button>
      </div>

      {error && <p className="text-[11px] text-rose-400">{error}</p>}

      {content.kind === 'audio_stream' || content.kind === 'podcast' ? (
        <audio
          ref={audioRef}
          src={content.url.toLowerCase().includes('.m3u8') ? undefined : content.url}
          controls
          autoPlay
          onEnded={handleEnded}
          onError={handleError}
          className="w-full"
        />
      ) : null}

      {content.kind === 'video' && isYoutubeEmbed ? (
        <div className="aspect-video w-full">
          <iframe
            src={`https://www.youtube.com/embed/${encodeURIComponent(youtubeId)}?autoplay=1`}
            allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
            className="w-full h-full rounded-xl"
            title={content.title ?? 'video'}
          />
        </div>
      ) : null}

      {content.kind === 'video' && !isYoutubeEmbed ? (
        <video
          ref={videoRef}
          src={content.url.toLowerCase().includes('.m3u8') ? undefined : content.url}
          controls
          autoPlay
          onEnded={handleEnded}
          onError={handleError}
          className="w-full rounded-xl bg-black"
        />
      ) : null}

      {content.kind === 'image' ? (
        <a href={content.url} target="_blank" rel="noopener noreferrer">
          <img
            src={content.url}
            alt={content.title ?? 'immagine'}
            className="w-full rounded-xl"
            loading="lazy"
          />
        </a>
      ) : null}

      {content.kind === 'document' ? (
        <iframe
          src={content.url}
          title={content.title ?? 'documento'}
          className="w-full h-72 rounded-xl bg-slate-100"
        />
      ) : null}
    </div>
  );
}

function kindLabel(k: CdaKind): string {
  return {
    audio_stream: '📻 RADIO',
    podcast: '🎙 PODCAST',
    video: '🎬 VIDEO',
    article: '📰 ARTICOLO',
    image: '🖼 IMMAGINE',
    document: '📄 DOC',
  }[k];
}
