import { useState } from 'react';

import { createFact } from '../api/memory';
import { stripToolsForDisplay } from '../lib/tools';
import type { Message } from '../types/chat';
import { Icon, cn, useToast } from '../design';

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  const toast = useToast();
  const [pinning, setPinning] = useState(false);
  const [pinned, setPinned] = useState(false);

  if (message.role === 'system') return null;

  const displayContent = isAssistant
    ? stripToolsForDisplay(message.content)
    : message.content;

  async function pinAsFact() {
    if (pinning || pinned || !message.content.trim()) return;
    setPinning(true);
    try {
      await createFact({
        text: message.content.slice(0, 500),
        type: 'personal',
        confidence: 1.0,
      });
      setPinned(true);
      toast.push({
        kind: 'celebrate',
        title: 'Salvato in memoria',
        body: 'Cara ricorderà questo fatto.',
      });
    } catch {
      toast.push({ kind: 'alert', title: 'Salvataggio fallito' });
    } finally {
      setPinning(false);
    }
  }

  return (
    <div
      className={cn(
        'group flex animate-rise items-end gap-1.5',
        isUser ? 'justify-end' : 'justify-start',
      )}
    >
      {/* Pin button — only on user bubbles, hover-revealed (mobile: always visible at low opacity). */}
      {isUser && !pinned && (
        <button
          type="button"
          onClick={() => void pinAsFact()}
          disabled={pinning}
          aria-label="Salva come fatto in memoria"
          title="Salva come fatto in memoria"
          className={cn(
            'shrink-0 h-8 w-8 rounded-pill text-fg-muted',
            'opacity-0 group-hover:opacity-100 md:opacity-0',
            'hover:text-celebrate hover:bg-celebrate/12',
            'transition-all duration-180 ease-spring',
            'flex items-center justify-center',
            pinning && 'opacity-100 animate-breathe',
          )}
        >
          <Icon name="spark" size={15} />
        </button>
      )}
      {isUser && pinned && (
        <span
          className="shrink-0 h-8 w-8 flex items-center justify-center text-celebrate"
          title="Salvato in memoria"
        >
          <Icon name="check" size={15} />
        </span>
      )}

      <div
        className={cn(
          'max-w-[82%] md:max-w-[72%] px-4 py-2.5 whitespace-pre-wrap break-words',
          'leading-relaxed text-[15px]',
          isUser
            ? 'rounded-2xl rounded-tr-sm bg-accent text-ivory shadow-warm'
            : 'rounded-2xl rounded-tl-sm bg-surface1 text-fg ring-1 ring-fg/8',
        )}
      >
        {displayContent || (isAssistant && (
          <span className="inline-flex gap-1 py-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-fg-muted animate-breathe" />
            <span
              className="h-1.5 w-1.5 rounded-full bg-fg-muted animate-breathe"
              style={{ animationDelay: '120ms' }}
            />
            <span
              className="h-1.5 w-1.5 rounded-full bg-fg-muted animate-breathe"
              style={{ animationDelay: '240ms' }}
            />
          </span>
        ))}

        {message.toolResults && message.toolResults.length > 0 && (
          <div className="mt-2.5 space-y-1.5">
            {message.toolResults.map((r, i) => (
              <div
                key={i}
                className={cn(
                  'flex items-start gap-2 rounded-md px-2.5 py-1.5 text-xs leading-snug',
                  r.ok
                    ? 'bg-ok/15 text-ok ring-1 ring-ok/30'
                    : 'bg-alert/15 text-alert ring-1 ring-alert/30',
                  isUser && 'bg-ivory/15 text-ivory ring-ivory/25',
                )}
              >
                <Icon name={r.ok ? 'check' : 'bell'} size={13} className="mt-0.5 shrink-0" />
                <span className="flex-1">{r.detail}</span>
              </div>
            ))}
          </div>
        )}

        {message.tokensPerSecond !== undefined && (
          <div
            className={cn(
              'mt-1.5 text-2xs flex items-center gap-2',
              isUser ? 'text-ivory/70' : 'text-fg-muted',
            )}
          >
            <span>{message.tokensPerSecond.toFixed(1)} tok/s</span>
            {message.firstTokenSeconds != null && (
              <>
                <span>·</span>
                <span>TTFT {message.firstTokenSeconds.toFixed(2)}s</span>
              </>
            )}
            {message.revised && (
              <span className={cn(isUser ? 'text-celebrate' : 'text-celebrate ml-1')}>
                · risposta rivista
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
