import { useState, type FormEvent } from 'react';
import { Plus } from '@phosphor-icons/react';
import { cn } from '@/lib/cn';

interface QuickAddInputProps {
  placeholder: string;
  onAdd: (text: string) => void | Promise<void>;
  disabled?: boolean;
}

export function QuickAddInput({ placeholder, onAdd, disabled }: QuickAddInputProps) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t || busy || disabled) return;
    setBusy(true);
    try {
      await onAdd(t);
      setText('');
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className={cn(
        'flex items-center gap-2 rounded-md bg-bg-elevated border border-border-soft',
        'focus-within:border-accent-coral focus-within:ring-2 focus-within:ring-accent-coral/20',
        'transition-all duration-base ease-smooth shadow-1',
      )}
    >
      <Plus size={20} weight="bold" className="ml-3 text-text-muted flex-shrink-0" />
      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        disabled={busy || disabled}
        className="flex-1 bg-transparent py-3 text-base text-text-primary placeholder:text-text-muted outline-none border-0"
      />
      <button
        type="submit"
        disabled={!text.trim() || busy || disabled}
        className={cn(
          'h-9 px-4 mr-1.5 rounded-sm text-sm font-medium',
          'bg-accent-coral text-text-inverse hover:bg-[#ff5252] transition-colors',
          'disabled:opacity-40 disabled:bg-border-strong',
        )}
      >
        Aggiungi
      </button>
    </form>
  );
}
