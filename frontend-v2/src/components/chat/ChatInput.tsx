import { useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { PaperPlaneTilt, Microphone } from '@phosphor-icons/react';
import { cn } from '@/lib/cn';

interface ChatInputProps {
  onSend: (text: string) => void | Promise<void>;
  onVoiceTap: () => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, onVoiceTap, disabled }: ChatInputProps) {
  const [text, setText] = useState('');
  const taRef = useRef<HTMLTextAreaElement>(null);

  function autosize() {
    const el = taRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    const t = text.trim();
    if (!t || disabled) return;
    setText('');
    if (taRef.current) taRef.current.style.height = 'auto';
    await onSend(t);
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  }

  return (
    <form
      onSubmit={submit}
      className="flex items-end gap-2 bg-bg-elevated border-t border-border-soft p-3 pb-[calc(env(safe-area-inset-bottom,0)+0.75rem)]"
    >
      <button
        type="button"
        onClick={onVoiceTap}
        disabled={disabled}
        aria-label="Parla"
        className={cn(
          'inline-flex items-center justify-center w-11 h-11 rounded-md flex-shrink-0',
          'bg-accent-coral/12 text-accent-coral hover:bg-accent-coral/20 transition-colors',
          'disabled:opacity-40',
        )}
      >
        <Microphone size={22} weight="duotone" />
      </button>
      <textarea
        ref={taRef}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          autosize();
        }}
        onKeyDown={onKey}
        rows={1}
        disabled={disabled}
        placeholder="Scrivi qualcosa…"
        className={cn(
          'flex-1 resize-none rounded-md border border-border-soft bg-bg-base',
          'px-3 py-2.5 text-base leading-relaxed outline-none',
          'focus:border-accent-coral focus:ring-2 focus:ring-accent-coral/20',
          'min-h-[2.75rem] max-h-[200px]',
        )}
      />
      <button
        type="submit"
        aria-label="Invia"
        disabled={disabled || !text.trim()}
        className={cn(
          'inline-flex items-center justify-center w-11 h-11 rounded-md flex-shrink-0',
          'bg-accent-coral text-text-inverse hover:bg-[#ff5252] transition-colors',
          'disabled:opacity-40 disabled:bg-border-strong',
        )}
      >
        <PaperPlaneTilt size={22} weight="fill" />
      </button>
    </form>
  );
}
