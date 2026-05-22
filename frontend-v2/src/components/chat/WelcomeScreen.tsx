import { motion } from 'framer-motion';
import { CaraFace } from '@/components/avatar/CaraFace';
import { Card } from '@/design/components';

interface WelcomeScreenProps {
  userName?: string;
  onSuggestion: (text: string) => void;
}

const SUGGESTIONS = [
  'Cosa devo fare oggi?',
  'Aggiungi pomodori alla spesa',
  'Ricordami di chiamare il dottore alle 11',
  'Che tempo fa?',
  'Quali sono le novità nelle news?',
  'Spegni le luci del salotto',
];

export function WelcomeScreen({ userName, onSuggestion }: WelcomeScreenProps) {
  const firstName = (userName ?? '').split(' ')[0] || 'tu';
  return (
    <div className="container-app pt-8 pb-4 text-center">
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.4, ease: [0.2, 0, 0, 1] }}
      >
        <div className="inline-block mb-4">
          <CaraFace size={140} energy="idle" emotion="happy" />
        </div>
        <h1 className="font-display text-3xl text-text-primary">Ciao {firstName}</h1>
        <p className="mt-2 text-text-secondary">
          Cosa posso fare per te?
        </p>
      </motion.div>

      <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-md mx-auto">
        {SUGGESTIONS.map((s, i) => (
          <motion.button
            key={s}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 + i * 0.05 }}
            onClick={() => onSuggestion(s)}
            className="text-left"
          >
            <Card padding="base" elevation={0} className="hover:bg-bg-surface transition-colors h-full">
              <p className="text-sm text-text-primary">{s}</p>
            </Card>
          </motion.button>
        ))}
      </div>
    </div>
  );
}
