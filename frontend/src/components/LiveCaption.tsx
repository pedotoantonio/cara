/**
 * Live caption / karaoke-style subtitles for CARA's voice replies.
 *
 * Two modes:
 *   - role="user":      shows what STT is hearing right now (interim
 *                       transcript, single rolling line).
 *   - role="assistant": follows the TTS via `onSpeakEvent` from
 *                       `lib/speech.ts`. Each `pulse` event tells us
 *                       which word the synth just started speaking; we
 *                       advance the highlight cursor until the end.
 *
 * The component owns its own subscription so the parent only has to feed
 * it the *full* spoken text once (when streaming finishes).
 */

import { useEffect, useRef, useState } from 'react';

import { onSpeakEvent } from '../lib/speech';

interface LiveCaptionProps {
  text: string;
  role: 'user' | 'assistant';
  /** Hide entirely when text is empty (otherwise we keep the slot reserved). */
  collapseEmpty?: boolean;
}

export function LiveCaption({ text, role, collapseEmpty = false }: LiveCaptionProps) {
  const words = useTokenize(text);
  const [spokenIdx, setSpokenIdx] = useState(0);
  const cursorRef = useRef(0);

  // Reset cursor when the text changes (new utterance).
  useEffect(() => {
    cursorRef.current = 0;
    setSpokenIdx(role === 'user' ? words.length : 0);
  }, [text, role, words.length]);

  // Subscribe to TTS pulse events only for assistant captions.
  useEffect(() => {
    if (role !== 'assistant' || words.length === 0) return;
    return onSpeakEvent((ev) => {
      if (ev.type === 'start') {
        cursorRef.current = 0;
        setSpokenIdx(0);
      } else if (ev.type === 'pulse') {
        const w = (ev.word ?? '').trim().toLowerCase();
        if (!w) return;
        // Advance the cursor to the next word that loosely matches the pulse.
        // Because chunk boundaries reset the speech engine's char index, we
        // move forward until we find a word starting with the same letters,
        // then stop. Worst case: one word out of sync — acceptable for UX.
        const start = cursorRef.current;
        for (let i = start; i < Math.min(start + 6, words.length); i++) {
          if (words[i].toLowerCase().startsWith(w.slice(0, 3))) {
            cursorRef.current = i + 1;
            setSpokenIdx(i + 1);
            return;
          }
        }
        // Fallback: just advance by one.
        cursorRef.current = Math.min(start + 1, words.length);
        setSpokenIdx(cursorRef.current);
      } else if (ev.type === 'end') {
        cursorRef.current = words.length;
        setSpokenIdx(words.length);
      }
    });
  }, [role, words]);

  if (collapseEmpty && !text) return null;

  const isUser = role === 'user';
  return (
    <div
      className={`text-center max-w-3xl mx-auto px-4 ${
        isUser ? 'text-slate-300' : 'text-slate-100'
      }`}
      aria-live="polite"
    >
      {!text ? (
        <span className="text-slate-600 italic text-base">…</span>
      ) : (
        <p className="text-2xl md:text-3xl leading-snug font-light tracking-tight">
          {words.map((w, i) => (
            <span
              key={`${w}-${i}`}
              className={
                isUser
                  ? 'text-slate-300'
                  : i < spokenIdx
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
      {isUser && text && (
        <p className="text-[11px] text-slate-500 mt-1 uppercase tracking-wider">
          tu
        </p>
      )}
    </div>
  );
}

function useTokenize(text: string): string[] {
  const [out, setOut] = useState<string[]>([]);
  useEffect(() => {
    setOut((text ?? '').split(/\s+/).filter(Boolean));
  }, [text]);
  return out;
}
