/**
 * expressionFromText — heuristic Italian text → CaraFace emotion.
 *
 * Used by HomePage and Chat to drive the avatar so the face reacts to what
 * CARA is actually saying, instead of a static "happy" while speaking.
 *
 * The rules are intentionally small and ordered most-specific-first. The
 * 1.5B model speaks Italian, so all patterns are IT-leaning with a few
 * common emoji/symbols thrown in.
 */

import type { Emotion } from '../components/CaraFace';

interface Rule {
  emotion: Emotion;
  test: RegExp;
}

const RULES: Rule[] = [
  // Error / can't do.
  {
    emotion: 'error',
    test: /\b(errore|non posso|non riesco|non sono in grado|non è (?:possibile|disponibile)|impossibile|qualcosa è andato storto|non ho potuto|fallito|fallisce|non funziona|non disponibile)\b|⚠️|❌/i,
  },
  // Empathy / regret.
  {
    emotion: 'sad',
    test: /\b(mi dispiace|peccato|purtroppo|spiacente|che tristezza|condoglianze|sono triste|che peccato|mi rincresce|amareggiat[oa])\b|😢|😔/i,
  },
  // Affection.
  {
    emotion: 'love',
    test: /\b(ti voglio bene|ti adoro|un abbraccio|ti abbraccio|con affetto|caro mio|cara mia|tesoro|amore mio)\b|💗|❤️|🤗|💖/i,
  },
  // Celebration — checked before plain happy so "auguri!" wins.
  {
    emotion: 'joyful',
    test: /\b(auguri|congratulazioni|complimenti|fantastico|favoloso|stupendo|magnifico|eccellente|evvai|fortissimo|spettacolare|grandioso|meraviglios[oa]|felicissim[oa]|che bello|hurr[aà])\b|🎉|🥳|!{2,}/i,
  },
  // Surprise.
  {
    emotion: 'surprised',
    test: /\b(davvero|sul serio|wow|perbacco|non ci credo|incredibile|cavolo|ma dai|caspita|però|guarda guarda)\b\s*[\?!]?|😲|😯/i,
  },
  // Confusion.
  {
    emotion: 'confused',
    test: /\b(non ho capito|non capisco|puoi ripetere|puoi rispiegarmi|non sono sicur[oa]|che intendi|cosa intendi|in che senso|chiarisci|non mi è chiaro)\b|🤔|❓/i,
  },
  // Reflection / hedged answer — typical of small models.
  {
    emotion: 'thoughtful',
    test: /\b(forse|probabilmente|dipende|non saprei|valuto|considerando|sembrerebbe|magari|potrebbe|hmm+|in effetti|riflettendo|a pensarci|possibile che|in genere|di solito|tendenzialmente|verosimilmente)\b/i,
  },
  // Affirmative / completed / friendly default — broad on purpose.
  {
    emotion: 'happy',
    test: /\b(perfetto|fatto|aggiunt[oa]|salvat[oa]|completat[oa]|ottimo|certo|sicuro|ecco|eccoti|eccoci|va bene|benissimo|volentieri|d'accordo|come desideri|pronto|pront[ao] a|ce l'ho|grazie|ciao|buongiorno|buonasera|buonanotte|sono qui|son[oa] tutt[oa] a|al tuo servizio|dimmi pure|ti ascolto|capito|chiaro|certamente|naturalmente|esatto|giusto|corretto|sì)\b|👍|✅|😊|🙂/i,
  },
];

/**
 * Infer a CaraFace emotion from the assistant's reply text.
 * Returns 'neutral' for empty / unrecognisable text. Non-empty text that
 * doesn't match any specific rule defaults to 'happy' so the avatar
 * always looks engaged when CARA is talking, instead of staying neutral.
 */
export function inferEmotion(text: string | undefined | null): Emotion {
  if (!text) return 'neutral';
  const stripped = text.trim();
  if (!stripped) return 'neutral';
  // Long replies: bias toward the closing sentences so the final tone wins.
  const tail = stripped.length > 240 ? stripped.slice(-240) : stripped;
  for (const rule of RULES) {
    if (rule.test.test(tail)) return rule.emotion;
  }
  // Friendly default: any non-empty assistant text → happy. Avoids the
  // "frozen face" problem where a generic reply leaves the avatar idle.
  return 'happy';
}
