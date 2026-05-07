import type { Config } from 'tailwindcss';
import {
  palette,
  semantic,
  fonts,
  fontSize,
  radius,
  shadow,
  motion,
  breakpoints,
} from './src/design/tokens';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['class', '[data-theme="night"]'],
  theme: {
    screens: breakpoints,
    extend: {
      colors: {
        // Raw palette (use sparingly — prefer semantic tokens).
        ivory:        palette.ivory,
        'ivory-warm': palette.ivoryWarm,
        sand:         palette.sand,
        terracotta:   palette.terracotta,
        'terracotta-dk': palette.terracottaDk,
        brick:        palette.brick,
        sage:         palette.sage,
        'sage-light': palette.sageLight,
        gold:         palette.gold,
        ink:          palette.ink,
        'ink-soft':   palette.inkSoft,
        'ink-muted':  palette.inkMuted,
        night:        palette.night,
        'night-surface': palette.nightSurface,
        'night-rise':    palette.nightRise,
        starlight:    palette.starlight,
        'starlight-soft': palette.starlightSoft,
        amber:        palette.amber,
        'twilight-sage': palette.twilightSage,

        // Semantic — bound to CSS vars in index.css (so day↔night swap works).
        bg:         'rgb(var(--c-bg) / <alpha-value>)',
        surface1:   'rgb(var(--c-surface1) / <alpha-value>)',
        surface2:   'rgb(var(--c-surface2) / <alpha-value>)',
        accent:     'rgb(var(--c-accent) / <alpha-value>)',
        'accent-dark': 'rgb(var(--c-accent-dark) / <alpha-value>)',
        alert:      'rgb(var(--c-alert) / <alpha-value>)',
        ok:         'rgb(var(--c-ok) / <alpha-value>)',
        'ok-soft':  'rgb(var(--c-ok-soft) / <alpha-value>)',
        celebrate:  'rgb(var(--c-celebrate) / <alpha-value>)',
        fg:         'rgb(var(--c-text) / <alpha-value>)',
        'fg-soft':  'rgb(var(--c-text-soft) / <alpha-value>)',
        'fg-muted': 'rgb(var(--c-text-muted) / <alpha-value>)',
      },
      fontFamily: {
        display: fonts.display.split(',').map(s => s.trim().replace(/^"|"$/g, '')),
        sans:    fonts.body.split(',').map(s => s.trim().replace(/^"|"$/g, '')),
        mono:    fonts.mono.split(',').map(s => s.trim().replace(/^"|"$/g, '')),
      },
      fontSize: fontSize as Record<string, [string, { lineHeight: string; letterSpacing?: string }]>,
      borderRadius: {
        sm: radius.sm,
        md: radius.md,
        lg: radius.lg,
        xl: radius.xl,
        '2xl': radius['2xl'],
        pill: radius.pill,
      },
      boxShadow: {
        soft:  shadow.soft,
        warm:  shadow.warm,
        deep:  shadow.deep,
        inset: shadow.inset,
      },
      transitionTimingFunction: {
        spring:  motion.spring,
        breathe: motion.breathe,
        snap:    motion.snap,
      },
      transitionDuration: {
        120: motion.duration.instant.replace('ms',''),
        180: motion.duration.quick.replace('ms',''),
        260: motion.duration.normal.replace('ms',''),
        420: motion.duration.slow.replace('ms',''),
        640: motion.duration.settle.replace('ms',''),
      },
      keyframes: {
        breathe: {
          '0%, 100%': { transform: 'scale(1)', opacity: '0.92' },
          '50%':      { transform: 'scale(1.02)', opacity: '1' },
        },
        rise: {
          '0%':   { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        sway: {
          '0%, 100%': { transform: 'rotate(-1deg)' },
          '50%':      { transform: 'rotate(1deg)' },
        },
        // Wall mic transcript: scrolls long text horizontally on a
        // single line, looping from right to left. Two copies of the
        // text are rendered side-by-side so the loop is seamless.
        'marquee-x': {
          '0%':   { transform: 'translateX(0%)' },
          '100%': { transform: 'translateX(-50%)' },
        },
      },
      animation: {
        breathe: 'breathe 3.6s cubic-bezier(0.45, 0, 0.55, 1) infinite',
        rise:    'rise 420ms cubic-bezier(0.22, 1, 0.36, 1) both',
        sway:    'sway 5s cubic-bezier(0.45, 0, 0.55, 1) infinite',
        'marquee-x': 'marquee-x 18s linear infinite',
      },
    },
  },
  plugins: [
    // Inject theme CSS vars on :root and [data-theme="night"].
    function({ addBase }: { addBase: (rules: Record<string, Record<string, string>>) => void }) {
      const toRgb = (hex: string) => {
        const v = hex.replace('#','');
        const n = parseInt(v.length === 3 ? v.split('').map(c => c+c).join('') : v, 16);
        return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
      };
      addBase({
        ':root': {
          '--c-bg':           toRgb(semantic.day.bg),
          '--c-surface1':     toRgb(semantic.day.surface1),
          '--c-surface2':     toRgb(semantic.day.surface2),
          '--c-accent':       toRgb(semantic.day.accent),
          '--c-accent-dark':  toRgb(semantic.day.accentDark),
          '--c-alert':        toRgb(semantic.day.alert),
          '--c-ok':           toRgb(semantic.day.ok),
          '--c-ok-soft':      toRgb(semantic.day.okSoft),
          '--c-celebrate':    toRgb(semantic.day.celebrate),
          '--c-text':         toRgb(semantic.day.text),
          '--c-text-soft':    toRgb(semantic.day.textSoft),
          '--c-text-muted':   toRgb(semantic.day.textMuted),
          color: 'rgb(var(--c-text))',
          backgroundColor: 'rgb(var(--c-bg))',
        },
        '[data-theme="night"]': {
          '--c-bg':           toRgb(semantic.night.bg),
          '--c-surface1':     toRgb(semantic.night.surface1),
          '--c-surface2':     toRgb(semantic.night.surface2),
          '--c-accent':       toRgb(semantic.night.accent),
          '--c-accent-dark':  toRgb(semantic.night.accentDark),
          '--c-alert':        toRgb(semantic.night.alert),
          '--c-ok':           toRgb(semantic.night.ok),
          '--c-ok-soft':      toRgb(semantic.night.okSoft),
          '--c-celebrate':    toRgb(semantic.night.celebrate),
          '--c-text':         toRgb(semantic.night.text),
          '--c-text-soft':    toRgb(semantic.night.textSoft),
          '--c-text-muted':   toRgb(semantic.night.textMuted),
        },
      });
    },
  ],
} satisfies Config;
