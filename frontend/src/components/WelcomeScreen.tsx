import { useReactions } from '../lib/reactions';
import { Icon, cn } from '../design';
import { CaraFaceFX } from './CaraFaceFX';

interface WelcomeScreenProps {
  userName: string;
  onPick: (suggestion: string) => void;
}

const SUGGESTIONS = [
  { label: 'Chi sei?',          prompt: 'Ciao Cara, chi sei?',                        icon: 'mood'    as const },
  { label: 'Cosa puoi fare?',   prompt: 'Cosa sai fare? Dimmi tutte le tue funzionalità.', icon: 'sparkle' as const },
  { label: 'Aggiungi una task', prompt: 'Ricordami di comprare il pane domani.',        icon: 'task'    as const },
  { label: 'Le news di oggi',   prompt: 'Quali sono le notizie principali del mondo oggi?', icon: 'news' as const },
  { label: 'Memoria',           prompt: 'Riesci a ricordare le cose che ti dico durante la conversazione? Fammi un esempio.', icon: 'spark' as const },
  { label: 'Roadmap',           prompt: 'Quali funzionalità arriveranno in futuro? Cosa avrai presto?', icon: 'calendar' as const },
];

const HINTS = [
  { icon: 'chat'   as const, text: 'Chiacchiera in italiano, con memoria della conversazione.' },
  { icon: 'task'   as const, text: 'Crea task, lista spesa, note rapide con la voce o il testo.' },
  { icon: 'family' as const, text: 'Riconosce chi è davanti alla camera e adatta il profilo.' },
];

export function WelcomeScreen({ userName, onPick }: WelcomeScreenProps) {
  const reactions = useReactions();
  return (
    <div className="h-full flex items-center justify-center px-4 py-6">
      <div className="max-w-xl w-full space-y-6 text-center">
        <div className="flex justify-center">
          <CaraFaceFX
            energy="idle"
            emotion="joyful"
            size={132}
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

        <p className="text-2xs text-fg-muted">Tocca o accarezza Cara</p>

        <div className="space-y-2.5">
          <h1 className="font-display text-3xl md:text-4xl text-fg leading-tight">
            Ciao {userName}
          </h1>
          <p className="text-sm text-fg-soft max-w-md mx-auto leading-relaxed">
            Sono <span className="text-accent font-medium">Cara</span>, l'assistente AI di
            casa. Posso aiutarti a coordinare la giornata, ricordare quello che conta, e
            ascoltare quando hai bisogno.
          </p>
        </div>

        <ul className="text-left text-sm text-fg space-y-2 inline-block">
          {HINTS.map((h) => (
            <li key={h.text} className="flex items-start gap-2.5">
              <span className="text-accent mt-0.5 shrink-0">
                <Icon name={h.icon} size={16} />
              </span>
              <span>{h.text}</span>
            </li>
          ))}
        </ul>

        <div className="pt-2">
          <p className="text-xs uppercase tracking-wider text-fg-muted mb-3">
            Prova a chiedermi
          </p>
          <div className="flex flex-wrap gap-2 justify-center">
            {SUGGESTIONS.map((s) => (
              <button
                key={s.label}
                type="button"
                onClick={() => onPick(s.prompt)}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-pill',
                  'bg-surface1 hover:bg-accent/12 hover:text-accent-dark',
                  'ring-1 ring-fg/8 hover:ring-accent/30',
                  'px-3 py-1.5 text-xs font-medium text-fg',
                  'transition-all duration-180 ease-spring',
                )}
              >
                <Icon name={s.icon} size={13} />
                {s.label}
              </button>
            ))}
          </div>
        </div>

        <p className="text-2xs text-fg-muted pt-2">
          Più funzioni in arrivo: calendario, integrazione casa, scoperta contenuti…
        </p>
      </div>
    </div>
  );
}
