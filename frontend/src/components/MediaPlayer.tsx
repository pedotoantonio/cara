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
  // True when the browser blocked the autoplay attempt — we then show a
  // big "▶ Tocca per riprodurre" overlay that the user can tap.
  const [needsTap, setNeedsTap] = useState(false);

  // Try to play automatically once the audio/video element mounts with src.
  // The user-gesture from the chat send may already be invalidated by the
  // 3-5 s discovery delay, so we expect this to fail on stricter browsers
  // (mobile Safari especially) and fall back to a visible tap overlay.
  useEffect(() => {
    if (content.kind !== 'audio_stream' && content.kind !== 'podcast' && content.kind !== 'video') {
      return;
    }
    const el = (content.kind === 'video' ? videoRef.current : audioRef.current) as
      | HTMLMediaElement
      | null;
    if (!el) return;
    // YouTube embed iframe handles its own autoplay via URL param.
    if (content.kind === 'video' && content.metadata?.embed) return;
    let cancelled = false;
    const t = setTimeout(() => {
      if (cancelled) return;
      el.play()
        .then(() => setNeedsTap(false))
        .catch(() => setNeedsTap(true));
    }, 80);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [content.url, content.kind, content.metadata?.embed]);

  function userTapPlay() {
    const el = (content.kind === 'video' ? videoRef.current : audioRef.current) as
      | HTMLMediaElement
      | null;
    if (!el) return;
    el.play()
      .then(() => setNeedsTap(false))
      .catch((e: Error) => {
        setError(`Riproduzione bloccata: ${e.message}`);
      });
  }

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
        <div className="relative">
          <audio
            ref={audioRef}
            src={content.url.toLowerCase().includes('.m3u8') ? undefined : content.url}
            controls
            onEnded={handleEnded}
            onError={handleError}
            onPlaying={() => setNeedsTap(false)}
            className="w-full"
          />
          {needsTap && (
            <button
              type="button"
              onClick={userTapPlay}
              className="absolute inset-0 flex items-center justify-center
                         bg-slate-900/80 backdrop-blur-sm rounded-lg gap-2
                         text-emerald-300 hover:text-emerald-200 text-sm font-medium"
            >
              <span className="text-3xl">▶</span>
              <span>Tocca per riprodurre</span>
            </button>
          )}
        </div>
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
        <div className="relative">
          <video
            ref={videoRef}
            src={content.url.toLowerCase().includes('.m3u8') ? undefined : content.url}
            controls
            onEnded={handleEnded}
            onError={handleError}
            onPlaying={() => setNeedsTap(false)}
            className="w-full rounded-xl bg-black"
          />
          {needsTap && (
            <button
              type="button"
              onClick={userTapPlay}
              className="absolute inset-0 flex items-center justify-center
                         bg-slate-900/70 backdrop-blur-sm rounded-xl gap-2
                         text-emerald-300 hover:text-emerald-200 text-sm font-medium"
            >
              <span className="text-4xl">▶</span>
              <span>Tocca per riprodurre</span>
            </button>
          )}
        </div>
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
