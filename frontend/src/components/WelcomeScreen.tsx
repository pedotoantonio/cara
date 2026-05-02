import { useEffect, useState } from 'react';

import { whoIsHome, type PersonAtHome } from '../api/family';
import { useReactions } from '../lib/reactions';
import { CaraFaceFX } from './CaraFaceFX';

interface WelcomeScreenProps {
  userName: string;
  onPick: (suggestion: string) => void;
}

const SUGGESTIONS = [
  { label: 'Chi sei?', prompt: 'Ciao CARA, chi sei?' },
  { label: 'Cosa puoi fare?', prompt: 'Cosa sai fare? Dimmi tutte le tue funzionalità.' },
  {
    label: 'Aggiungi una task',
    prompt: 'Ricordami di comprare il pane domani.',
  },
  {
    label: 'Chi è in casa?',
    prompt: 'Chi è in casa adesso?',
  },
  {
    label: 'Le news di oggi',
    prompt: 'Quali sono le notizie principali del mondo oggi?',
  },
  {
    label: 'Memoria',
    prompt: 'Riesci a ricordare le cose che ti dico durante la conversazione? Fammi un esempio.',
  },
  {
    label: 'Roadmap',
    prompt: 'Quali funzionalità arriveranno in futuro? Cosa avrai presto?',
  },
];

function PresenceBadge() {
  const [people, setPeople] = useState<PersonAtHome[] | null>(null);
  const [available, setAvailable] = useState(true);

  useEffect(() => {
    whoIsHome(15)
      .then((r) => setPeople(r.people))
      .catch(() => setAvailable(false));
  }, []);

  if (!available || people === null) return null;
  if (people.length === 0) {
    return (
      <p className="text-xs text-slate-500">In questo momento non vedo nessuno in casa.</p>
    );
  }
  const names = people.map((p) => p.name).join(', ');
  return (
    <p className="text-xs text-slate-400">
      <span className="text-emerald-400">●</span> In casa adesso: {names}
    </p>
  );
}

export function WelcomeScreen({ userName, onPick }: WelcomeScreenProps) {
  const reactions = useReactions();
  return (
    <div className="h-full flex items-center justify-center">
      <div className="max-w-xl w-full space-y-6 text-center">
        <div className="flex justify-center">
          <CaraFaceFX
            energy="idle"
            emotion="joyful"
            size={140}
            gestures
            onTap={() =>
              reactions.trigger('wake', { message: `Ciao ${userName}!` })
            }
            onSwipe={() => reactions.trigger('celebrate', { message: 'Mmh, mi piace.' })}
            onLongPress={() =>
              reactions.trigger('celebrate', { message: 'Sto ascoltando…' })
            }
          />
        </div>
        <p className="text-[11px] text-slate-600">Tocca o accarezza CARA</p>
        <div className="space-y-2">
          <p className="text-4xl font-light tracking-tight">Ciao {userName} 👋</p>
          <p className="text-slate-400">
            Sono <span className="text-emerald-400 font-medium">CARA</span>, l'assistente AI di
            casa. Posso aiutarti a:
          </p>
          <PresenceBadge />
        </div>

        <ul className="text-left text-sm text-slate-300 space-y-1.5 inline-block">
          <li>💬 Chiacchierare e rispondere a domande in italiano</li>
          <li>🧠 Ricordare nomi e dettagli durante la conversazione</li>
          <li>📚 Conservare le tue chat e riprenderle quando vuoi</li>
        </ul>

        <div className="pt-2">
          <p className="text-xs text-slate-500 mb-3">Prova a chiedermi:</p>
          <div className="flex flex-wrap gap-2 justify-center">
            {SUGGESTIONS.map((s) => (
              <button
                key={s.label}
                type="button"
                onClick={() => onPick(s.prompt)}
                className="rounded-full bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-1.5 text-xs text-slate-200 transition"
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        <p className="text-xs text-slate-600 pt-4">
          Più funzioni in arrivo: calendario, lista della spesa, integrazione casa…
        </p>
      </div>
    </div>
  );
}
