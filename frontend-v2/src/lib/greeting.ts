// Greeting personalizzato basato su orario + persona.

import type { ToneKey } from '@/api/auth';

export function timeOfDay(d = new Date()): 'morning' | 'afternoon' | 'evening' | 'night' {
  const h = d.getHours();
  if (h >= 5 && h < 12) return 'morning';
  if (h >= 12 && h < 18) return 'afternoon';
  if (h >= 18 && h < 22) return 'evening';
  return 'night';
}

const GREETINGS: Record<ToneKey, Record<ReturnType<typeof timeOfDay>, string>> = {
  default: {
    morning: 'Buongiorno {name}',
    afternoon: 'Ciao {name}',
    evening: 'Buonasera {name}',
    night: 'Ehi {name}',
  },
  calmo: {
    morning: 'Piano piano, buongiorno {name}',
    afternoon: 'Ben tornato {name}',
    evening: 'Sera tranquilla, {name}',
    night: 'Notte calma, {name}',
  },
  energico: {
    morning: 'Buongiorno {name}! Andiamo',
    afternoon: 'Forza {name}, si va!',
    evening: 'Sera attiva, {name}',
    night: 'Ancora qui {name}!',
  },
  formale: {
    morning: 'Buongiorno, {name}',
    afternoon: 'Buon pomeriggio, {name}',
    evening: 'Buonasera, {name}',
    night: 'È tardi, {name}',
  },
  playful: {
    morning: 'Ehi {name}, già in piedi?',
    afternoon: 'Tutto bene {name}?',
    evening: 'Sera sera, {name}',
    night: 'Nottambulo {name}!',
  },
};

const SUBTITLES: Record<ReturnType<typeof timeOfDay>, string[]> = {
  morning: [
    'Sono qui per la tua giornata',
    'Cosa facciamo oggi?',
    'Hai dormito bene?',
  ],
  afternoon: [
    'Come va il pomeriggio?',
    'Tutto sotto controllo?',
    'Ti serve qualcosa?',
  ],
  evening: [
    'Pomeriggio finito, sera comincia',
    'Una pausa meritata',
    'Cosa cucini stasera?',
  ],
  night: [
    'Hai pensato a domani?',
    'Tutto pronto per la notte',
    'Una sola cosa prima di dormire?',
  ],
};

export function buildGreeting(
  fullName: string | null | undefined,
  tone: ToneKey | null | undefined,
): { title: string; subtitle: string } {
  const firstName = (fullName ?? '').split(' ')[0] || 'tu';
  const t = tone ?? 'default';
  const part = timeOfDay();
  const template = GREETINGS[t][part];
  const title = template.replace('{name}', firstName);
  const list = SUBTITLES[part];
  const subtitle = list[Math.floor(Date.now() / 60_000) % list.length]!;
  return { title, subtitle };
}
