// CARA PWA v2 — design tokens (TypeScript)
//
// Mirror dei valori in tailwind.config.ts, esposti come oggetto TS per
// quando servono in JS (es. inline style dinamico, calcoli, motion props).

export const colors = {
  bg: {
    base: '#FFFFFF',
    surface: '#F7F8FA',
    elevated: '#FFFFFF',
  },
  border: {
    soft: '#E8EAEE',
    strong: '#C7CAD1',
  },
  text: {
    primary: '#0E1116',
    secondary: '#4B5563',
    muted: '#9AA0AB',
    inverse: '#FFFFFF',
  },
  accent: {
    coral: '#FF6B6B',
    mint: '#2EC4B6',
    sun: '#FFD166',
    sky: '#4ECDC4',
    lilac: '#9381FF',
    rose: '#FFB5C5',
    grass: '#06D6A0',
    clay: '#E76F51',
  },
} as const;

export type AccentToken = keyof typeof colors.accent;

export const accentForCategory = {
  voice: 'coral',
  task: 'mint',
  shopping: 'rose',
  note: 'sun',
  news: 'clay',
  radio: 'clay',
  memory: 'lilac',
  persona: 'lilac',
  smarthome: 'grass',
  weather: 'sky',
  admin: 'coral',
} as const satisfies Record<string, AccentToken>;

export type Category = keyof typeof accentForCategory;

/** Glow-color (rgba con alpha bassa) per ogni accent — usato sull'avatar */
export const glowFor: Record<AccentToken, string> = {
  coral: 'rgba(255, 107, 107, 0.25)',
  mint: 'rgba(46, 196, 182, 0.25)',
  sun: 'rgba(255, 209, 102, 0.30)',
  sky: 'rgba(78, 205, 196, 0.25)',
  lilac: 'rgba(147, 129, 255, 0.25)',
  rose: 'rgba(255, 181, 197, 0.30)',
  grass: 'rgba(6, 214, 160, 0.25)',
  clay: 'rgba(231, 111, 81, 0.25)',
};

export const motion = {
  quick: 0.12,
  base: 0.22,
  smooth: 0.4,
  spring: 0.5,
  slow: 0.8,
} as const;

export const easing = {
  smooth: [0.2, 0, 0, 1] as const,
  spring: [0.3, 1.4, 0.4, 1] as const,
};
