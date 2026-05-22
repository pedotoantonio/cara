import { useNavigate } from 'react-router-dom';
import {
  Microphone,
  CheckSquare,
  ShoppingCart,
  Note,
  ChatCircleDots,
  CalendarBlank,
  Sun,
} from '@phosphor-icons/react';
import { Sheet } from '@/design/components';
import { CaraFace } from '@/components/avatar/CaraFace';
import { useAuthStore } from '@/state/auth';
import { buildGreeting } from '@/lib/greeting';
import type { AccentToken } from '@/design/tokens';
import { cn } from '@/lib/cn';

interface AvatarDrawerProps {
  open: boolean;
  onClose: () => void;
  onVoice: () => void;
}

const ACCENT_BG: Record<AccentToken, string> = {
  coral: 'bg-accent-coral/12 text-accent-coral',
  mint: 'bg-accent-mint/12 text-accent-mint',
  sun: 'bg-accent-sun/20 text-[#8E6800]',
  sky: 'bg-accent-sky/12 text-accent-sky',
  lilac: 'bg-accent-lilac/12 text-accent-lilac',
  rose: 'bg-accent-rose/24 text-[#A53A5E]',
  grass: 'bg-accent-grass/12 text-accent-grass',
  clay: 'bg-accent-clay/12 text-accent-clay',
};

interface QuickAction {
  label: string;
  Icon: typeof Microphone;
  accent: AccentToken;
  onClick: () => void;
}

export function AvatarDrawer({ open, onClose, onVoice }: AvatarDrawerProps) {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const greeting = buildGreeting(user?.full_name, user?.tone_preference);

  const actions: QuickAction[] = [
    {
      label: 'Parla con me',
      Icon: Microphone,
      accent: 'coral',
      onClick: () => {
        onClose();
        onVoice();
      },
    },
    {
      label: 'Apri chat',
      Icon: ChatCircleDots,
      accent: 'lilac',
      onClick: () => {
        onClose();
        navigate('/chat');
      },
    },
    {
      label: 'Nuova task',
      Icon: CheckSquare,
      accent: 'mint',
      onClick: () => {
        onClose();
        navigate('/list/tasks');
      },
    },
    {
      label: 'Aggiungi alla spesa',
      Icon: ShoppingCart,
      accent: 'rose',
      onClick: () => {
        onClose();
        navigate('/list/shopping');
      },
    },
    {
      label: 'Nuova nota',
      Icon: Note,
      accent: 'sun',
      onClick: () => {
        onClose();
        navigate('/list/notes');
      },
    },
    {
      label: 'Calendario',
      Icon: CalendarBlank,
      accent: 'sky',
      onClick: () => {
        onClose();
        navigate('/life/calendar');
      },
    },
    {
      label: 'Meteo',
      Icon: Sun,
      accent: 'sun',
      onClick: () => {
        onClose();
        navigate('/life/meteo');
      },
    },
  ];

  return (
    <Sheet open={open} onClose={onClose}>
      <div className="text-center mb-4">
        <CaraFace size={96} energy="idle" emotion="happy" />
        <h2 className="font-display text-xl mt-3">{greeting.title}</h2>
        <p className="text-sm text-text-secondary">Cosa posso fare per te?</p>
      </div>

      <ul className="grid grid-cols-2 gap-2">
        {actions.map((a) => (
          <li key={a.label}>
            <button
              onClick={a.onClick}
              className="w-full flex flex-col items-center justify-center gap-2 py-4 rounded-md bg-bg-surface hover:bg-bg-base border border-border-soft transition-colors"
            >
              <span
                className={cn(
                  'inline-flex items-center justify-center w-12 h-12 rounded-md',
                  ACCENT_BG[a.accent],
                )}
              >
                <a.Icon size={24} weight="duotone" />
              </span>
              <span className="text-sm font-medium">{a.label}</span>
            </button>
          </li>
        ))}
      </ul>
    </Sheet>
  );
}
