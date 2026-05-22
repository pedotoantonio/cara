import type { Config } from 'tailwindcss';

// CARA PWA v2 — design tokens espressi in Tailwind.
// Lo sfondo dell'app è SEMPRE chiaro. Il colore vive nelle icone, nei
// bottoni primari e nelle accent — mai nello sfondo per superficie estesa.

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Sfondo neutro chiaro (default app)
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
        // 8 accent colorati — solo per icone, bottoni primari, illustrazioni
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
      },
      fontFamily: {
        ui: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        display: ['"Source Serif 4"', '"Times New Roman"', 'serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      fontSize: {
        // Scale modulare 1.200
        xs: ['12px', { lineHeight: '16px' }],
        sm: ['14px', { lineHeight: '20px' }],
        base: ['16px', { lineHeight: '24px' }],
        md: ['18px', { lineHeight: '28px' }],
        lg: ['21px', { lineHeight: '30px' }],
        xl: ['24px', { lineHeight: '32px' }],
        '2xl': ['28px', { lineHeight: '36px' }],
        '3xl': ['32px', { lineHeight: '40px' }],
        '4xl': ['40px', { lineHeight: '48px' }],
        '5xl': ['48px', { lineHeight: '56px' }],
      },
      borderRadius: {
        xs: '4px',
        sm: '8px',
        md: '12px',
        lg: '16px',
        xl: '24px',
        '2xl': '32px',
      },
      boxShadow: {
        '1': '0 1px 2px rgba(20, 24, 40, 0.04), 0 1px 1px rgba(20, 24, 40, 0.02)',
        '2': '0 4px 12px rgba(20, 24, 40, 0.06), 0 2px 4px rgba(20, 24, 40, 0.03)',
        '3': '0 12px 32px rgba(20, 24, 40, 0.08), 0 6px 12px rgba(20, 24, 40, 0.04)',
      },
      transitionTimingFunction: {
        smooth: 'cubic-bezier(0.2, 0, 0, 1)',
        spring: 'cubic-bezier(0.3, 1.4, 0.4, 1)',
      },
      transitionDuration: {
        quick: '120ms',
        base: '220ms',
        smooth: '400ms',
        spring: '500ms',
        slow: '800ms',
      },
      animation: {
        breathe: 'breathe 4s ease-in-out infinite',
        'pulse-soft': 'pulse-soft 2.5s ease-in-out infinite',
        'fade-in': 'fade-in 220ms ease-out',
        'slide-up': 'slide-up 280ms cubic-bezier(0.2, 0, 0, 1)',
      },
      keyframes: {
        breathe: {
          '0%, 100%': { transform: 'scale(1)' },
          '50%': { transform: 'scale(1.04)' },
        },
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.7' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'slide-up': {
          from: { transform: 'translateY(8px)', opacity: '0' },
          to: { transform: 'translateY(0)', opacity: '1' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
