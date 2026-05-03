/**
 * Live caption / karaoke-style subtitles for CARA's voice replies.
 *
 * - role="user":      shows what STT is hearing right now (interim
 *                     transcript, single rolling line, scrolls right-to-left).
 * - role="assistant": follows the TTS via `onSpeakEvent` from
 *                     `lib/speech.ts`. Each `pulse` event tells us which
 *                     word the synth just started speaking. We advance the
 *                     karaoke cursor and smoothly scroll the track so the
 *                     current word stays in view.
 *
 * Layout: a single horizontal line, never wraps, never overlaps the face
 * above or the mic below. Soft fade at the edges via `mask-image` so words
 * appear/disappear gracefully.
 *
 * Reduced motion: when the user prefers reduced motion, the scroll is
 * disabled and the text wraps normally with only the current word
 * highlighted in place.
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { onSpeakEvent } from '../lib/speech';

interface LiveCaptionProps {
  text: string;
  role: 'user' | 'assistant';
  /** Hide entirely when text is empty (otherwise we keep the slot reserved). */
  collapseEmpty?: boolean;
}

function tokenize(text: string): string[] {
  return (text ?? '').replace(/\s+/g, ' ').trim().split(' ').filter(Boolean);
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function LiveCaption({ text, role, collapseEmpty = false }: LiveCaptionProps) {
  const words = useMemo(() => tokenize(text), [text]);
  const [spokenIdx, setSpokenIdx] = useState(role === 'user' ? Number.MAX_SAFE_INTEGER : 0);
  const [fadingOut, setFadingOut] = useState(false);
  const cursorRef = useRef(0);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const wordSpansRef = useRef<HTMLSpanElement[]>([]);
  const reduced = prefersReducedMotion();

  // Reset state when the text identity changes (new message OR revision).
  useEffect(() => {
    cursorRef.current = 0;
    setSpokenIdx(role === 'user' ? Number.MAX_SAFE_INTEGER : 0);
    setFadingOut(false);
    if (trackRef.current) trackRef.current.style.transform = 'translateX(0px)';
  }, [text, role]);

  // Subscribe to the TTS event bus — only for assistant captions. The pulse
  // events come from real audio progress (browser SpeechSynthesis boundary
  // events for browser TTS, AudioContext.currentTime poll for Piper) so the
  // cursor stays in lock-step with the audio.
  useEffect(() => {
    if (role !== 'assistant' || words.length === 0) return;
    return onSpeakEvent((ev) => {
      if (ev.type === 'start') {
        cursorRef.current = 0;
        setSpokenIdx(0);
        setFadingOut(false);
      } else if (ev.type === 'pulse') {
        const w = (ev.word ?? '').trim().toLowerCase();
        if (!w) return;
        const start = cursorRef.current;
        // Match the pulse word against the next ~6 words by 3-letter prefix.
        // Falls back to advance-by-one so the cursor never gets stuck.
        for (let i = start; i < Math.min(start + 6, words.length); i++) {
          if (words[i].toLowerCase().startsWith(w.slice(0, 3))) {
            cursorRef.current = i + 1;
            setSpokenIdx(i + 1);
            return;
          }
        }
        cursorRef.current = Math.min(start + 1, words.length);
        setSpokenIdx(cursorRef.current);
      } else if (ev.type === 'end') {
        cursorRef.current = words.length;
        setSpokenIdx(words.length);
        // Linger 1 s so the user can read the last word, then fade out.
        const t1 = window.setTimeout(() => setFadingOut(true), 1000);
        return () => window.clearTimeout(t1);
      }
    });
  }, [role, words]);

  // Auto-scroll the track to keep the current word at ~40 % of the container
  // width. Computed in a DOM-effect so we have measured offsetLeft / width
  // values. Skipped when prefers-reduced-motion is active.
  useEffect(() => {
    if (reduced) return;
    if (role !== 'assistant') return;
    const track = trackRef.current;
    const container = containerRef.current;
    if (!track || !container) return;
    const focusIdx = Math.min(spokenIdx, words.length - 1);
    if (focusIdx < 0) return;
    const span = wordSpansRef.current[focusIdx];
    if (!span) return;
    const cw = container.clientWidth;
    const wordCenter = span.offsetLeft + span.offsetWidth / 2;
    const target = -(wordCenter - cw * 0.4);
    track.style.transform = `translate3d(${Math.round(target)}px,0,0)`;
  }, [spokenIdx, words, role, reduced]);

  if (collapseEmpty && !text) return null;

  const isUser = role === 'user';

  // -------- user mode: simple rolling transcript (single line, ends right) --------
  if (isUser) {
    return (
      <div
        className="text-center max-w-3xl mx-auto px-4 text-slate-300"
        aria-live="polite"
      >
        <div
          className="overflow-hidden whitespace-nowrap text-2xl md:text-3xl
                     leading-snug font-light tracking-tight"
          style={{ direction: 'rtl' }}
        >
          <span dir="ltr" className="inline-block">
            {text || '…'}
          </span>
        </div>
        {text && (
          <p className="text-[11px] text-slate-500 mt-1 uppercase tracking-wider">tu</p>
        )}
      </div>
    );
  }

  // -------- assistant mode: karaoke ticker --------
  if (reduced) {
    // Reduced-motion fallback: static multi-line text with cursor highlight.
    return (
      <div className="text-center max-w-3xl mx-auto px-4 text-slate-100" aria-live="polite">
        {!text ? (
          <span className="text-slate-600 italic text-base">…</span>
        ) : (
          <p className="text-2xl md:text-3xl leading-snug font-light tracking-tight">
            {words.map((w, i) => (
              <span
                key={`${w}-${i}`}
                className={
                  i < spokenIdx
                    ? 'text-slate-500'
                    : i === spokenIdx
                      ? 'text-emerald-200'
                      : 'text-slate-100/40'
                }
              >
                {w}
                {i < words.length - 1 ? ' ' : ''}
              </span>
            ))}
          </p>
        )}
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      role="status"
      aria-live="polite"
      className={`relative w-full overflow-hidden transition-opacity duration-700 ${
        fadingOut ? 'opacity-0' : 'opacity-100'
      }`}
      style={{
        // Soft fade at both edges so words enter / exit gracefully.
        WebkitMaskImage:
          'linear-gradient(90deg, transparent 0%, black 12%, black 88%, transparent 100%)',
        maskImage:
          'linear-gradient(90deg, transparent 0%, black 12%, black 88%, transparent 100%)',
        height: 'clamp(3.25rem, 7vh, 4.5rem)',
        display: 'flex',
        alignItems: 'center',
      }}
    >
      <div
        ref={trackRef}
        className="whitespace-nowrap text-2xl md:text-3xl leading-snug
                   font-light tracking-tight transition-transform duration-300 ease-out
                   pl-[40%]"
        style={{ willChange: 'transform' }}
      >
        {!text ? (
          <span className="text-slate-600 italic text-base">…</span>
        ) : (
          words.map((w, i) => (
            <span
              key={`${w}-${i}`}
              ref={(el) => {
                if (el) wordSpansRef.current[i] = el;
              }}
              className={
                i < spokenIdx - 1
                  ? 'text-slate-500'
                  : i === spokenIdx - 1
                    ? 'text-emerald-200'
                    : 'text-slate-300/60'
              }
            >
              {w}
              {i < words.length - 1 ? ' ' : ''}
            </span>
          ))
        )}
      </div>
    </div>
  );
}
