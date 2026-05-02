/**
 * Reader-mode for an article discovered by the CDA.
 *
 * Loads the original URL (the backend already extracted the body during
 * discovery, but the frontend uses the URL directly for "open original" and
 * lets the LLM-side `extracted` text appear via `metadata.text`).
 */

import { useEffect, useRef, useState } from 'react';

import { feedbackStarted, feedbackStopped } from '../api/cda';
import { speak, stopSpeaking } from '../lib/speech';

interface ArticleContent {
  url: string;
  title: string | null;
  source_domain: string | null;
  metadata: Record<string, unknown>;
  content_id: string;
}

export function ArticleReader({
  content,
  onClose,
}: {
  content: ArticleContent;
  onClose: () => void;
}) {
  const startedAt = useRef(performance.now());
  const reason = useRef<'user_stop' | 'ended' | 'error' | 'switched'>('user_stop');
  const [reading, setReading] = useState(false);

  useEffect(() => {
    feedbackStarted(content.content_id).catch(() => undefined);
    startedAt.current = performance.now();
    return () => {
      stopSpeaking();
      const playedSeconds = (performance.now() - startedAt.current) / 1000;
      feedbackStopped({
        content_id: content.content_id,
        played_seconds: playedSeconds,
        reason: reason.current,
      }).catch(() => undefined);
    };
  }, [content.content_id]);

  const text = (content.metadata?.text as string) ?? '';
  const author = (content.metadata?.author as string | null) ?? null;
  const date = (content.metadata?.date as string | null) ?? null;

  function readAloud() {
    if (reading) {
      stopSpeaking();
      setReading(false);
      return;
    }
    setReading(true);
    speak(`${content.title ?? ''}. ${text}`, {
      lang: 'it',
      onEnd: () => setReading(false),
    });
  }

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/95 overflow-y-auto p-4 md:p-8">
      <div className="max-w-2xl mx-auto space-y-4 text-slate-100">
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <h1 className="text-xl md:text-2xl font-semibold">
              {content.title ?? 'Articolo'}
            </h1>
            <p className="text-xs text-slate-500 mt-1">
              {[content.source_domain, author, date].filter(Boolean).join(' · ')}
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              reason.current = 'user_stop';
              onClose();
            }}
            className="text-slate-400 hover:text-slate-100 text-2xl leading-none"
            aria-label="Chiudi"
          >
            ✕
          </button>
        </div>

        <div className="flex gap-2 flex-wrap">
          <button
            type="button"
            onClick={readAloud}
            className="rounded-lg bg-emerald-600 hover:bg-emerald-500 px-3 py-2 text-sm"
          >
            {reading ? '⏹ Stop lettura' : '🔊 Leggimi l\'articolo'}
          </button>
          <a
            href={content.url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-2 text-sm"
          >
            Apri originale ↗
          </a>
        </div>

        {text ? (
          <div className="prose prose-invert max-w-none whitespace-pre-wrap text-[15px] leading-relaxed">
            {text}
          </div>
        ) : (
          <p className="text-sm text-slate-500">
            Non sono riuscita a estrarre il testo. Apri l'originale per leggerlo.
          </p>
        )}
      </div>
    </div>
  );
}
