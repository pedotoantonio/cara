import { stripToolsForDisplay } from '../lib/tools';
import type { Message } from '../types/chat';

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';

  if (message.role === 'system') return null;

  // For assistant turns, hide any `[TOOL: ...]` markup from the displayed
  // text — both finalised and still-streaming. The tool result is shown
  // separately as a coloured badge below.
  const displayContent = isAssistant
    ? stripToolsForDisplay(message.content)
    : message.content;

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2 whitespace-pre-wrap break-words ${
          isUser
            ? 'bg-emerald-600 text-white'
            : 'bg-slate-800 text-slate-100 border border-slate-700'
        }`}
      >
        {displayContent || (isAssistant && <span className="text-slate-400 italic">…</span>)}
        {message.toolResults && message.toolResults.length > 0 && (
          <div className="mt-2 space-y-1">
            {message.toolResults.map((r, i) => (
              <div
                key={i}
                className={`text-xs rounded-lg px-2 py-1 ${
                  r.ok
                    ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                    : 'bg-rose-500/15 text-rose-300 border border-rose-500/30'
                }`}
              >
                {r.ok ? '✓' : '⚠'} {r.detail}
              </div>
            ))}
          </div>
        )}
        {message.tokensPerSecond !== undefined && (
          <div className="mt-1 text-[10px] text-slate-400">
            {message.tokensPerSecond.toFixed(1)} tok/s · TTFT {message.firstTokenSeconds?.toFixed(2)}s
            {message.revised && (
              <span className="ml-2 text-amber-300">· risposta rivista</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
