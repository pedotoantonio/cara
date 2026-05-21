// Design tokens for CARA "Una pianta che respira nel salotto" identity.
// Day = avorio + terracotta + verde salvia, sera = blu notte profondo + oro.

export const palette = {
  // Day mode — light & airy, friendly per famiglia. Bg quasi bianco con
  // velo azzurrino freddo (come una pagina di carta sotto luce naturale).
  ivory:        '#F5F8FC', // background base — bianco-azzurrino chiarissimo
  ivoryWarm:    '#FFFFFF', // surface 1 — bianco puro, card "galleggiano"
  sand:         '#EAEFF6', // surface 2 — soft blue-gray
  terracotta:   '#F97C42', // primary accent — arancio acceso (era spento)
  terracottaDk: '#E0631F', // hover/pressed
  brick:        '#EF4444', // alert — rosso vivo
  sage:         '#10B981', // secondary, "ok / vivo" — verde emerald saturo
  sageLight:    '#34D399',
  gold:         '#F59E0B', // celebrazioni, badge — ambra saturo
  ink:          '#0F172A', // testo primario giorno — slate scuro
  inkSoft:      '#475569', // testo secondario
  inkMuted:     '#94A3B8', // hint / placeholder

  // Night mode — più profondo, contrasto basso, occhio rilassato.
  night:        '#0F1B2D', // background base sera
  nightSurface: '#172439', // surface 1
  nightRise:    '#22324F', // surface 2
  starlight:    '#F1E9D8', // testo primario sera
  starlightSoft:'#C8C0AE',
  amber:        '#F2B441', // accent caldo sera
  twilightSage: '#7AA8A2',
} as const;

export type PaletteKey = keyof typeof palette;

// Friendly semantic mapping. Components use these instead of raw colors so
// switching day↔night happens by swapping the layer.
export const semantic = {
  day: {
    bg:         palette.ivory,
    surface1:   palette.ivoryWarm,
    surface2:   palette.sand,
    accent:     palette.terracotta,
    accentDark: palette.terracottaDk,
    alert:      palette.brick,
    ok:         palette.sage,
    okSoft:     palette.sageLight,
    celebrate:  palette.gold,
    text:       palette.ink,
    textSoft:   palette.inkSoft,
    textMuted:  palette.inkMuted,
    divider:    'rgba(42,42,42,0.08)',
    overlay:    'rgba(42,42,42,0.40)',
  },
  night: {
    bg:         palette.night,
    surface1:   palette.nightSurface,
    surface2:   palette.nightRise,
    accent:     palette.amber,
    accentDark: palette.gold,
    alert:      palette.brick,
    ok:         palette.twilightSage,
    okSoft:     palette.sageLight,
    celebrate:  palette.amber,
    text:       palette.starlight,
    textSoft:   palette.starlightSoft,
    textMuted:  '#8E8675',
    divider:    'rgba(241,233,216,0.10)',
    overlay:    'rgba(0,0,0,0.55)',
  },
} as const;

export type SemanticTheme = typeof semantic.day;

// Typography (2026-05-20). Single-family serif system inspired by
// Utopia: body + display share Source Serif 4, with the optical-size
// axis doing the heavy lifting (small opsz for UI, larger opsz for
// titles). Source Serif 4 is open-source and the closest free webfont
// to Adobe's proprietary Utopia.
export const fonts = {
  display: '"Source Serif 4", "Source Serif Pro", Georgia, "Times New Roman", serif',
  body:    '"Source Serif 4", "Source Serif Pro", Georgia, "Times New Roman", serif',
  mono:    '"JetBrains Mono", ui-monospace, "SF Mono", monospace',
} as const;

// Modular type scale (1.250 — major third).
export const fontSize = {
  '2xs': ['0.6875rem', { lineHeight: '1rem',     letterSpacing: '0.01em' }],
  xs:    ['0.75rem',   { lineHeight: '1.125rem', letterSpacing: '0.005em' }],
  sm:    ['0.875rem',  { lineHeight: '1.25rem' }],
  base:  ['1rem',      { lineHeight: '1.5rem' }],
  md:    ['1.125rem',  { lineHeight: '1.625rem' }],
  lg:    ['1.25rem',   { lineHeight: '1.75rem' }],
  xl:    ['1.5rem',    { lineHeight: '2rem',     letterSpacing: '-0.005em' }],
  '2xl': ['1.875rem',  { lineHeight: '2.25rem',  letterSpacing: '-0.01em' }],
  '3xl': ['2.25rem',   { lineHeight: '2.5rem',   letterSpacing: '-0.015em' }],
  '4xl': ['2.75rem',   { lineHeight: '3rem',     letterSpacing: '-0.02em' }],
  '5xl': ['3.5rem',    { lineHeight: '3.75rem',  letterSpacing: '-0.025em' }],
} as const;

// 4-pt spacing scale (Tailwind base) extended with named "soft" sizes.
export const spacing = {
  hairline: '1px',
  page:     '1.25rem', // 20px - default page padding mobile
  pageDesktop: '2rem',
  card:     '1.5rem',  // padding interno card
  gutter:   '0.75rem', // gap tra elementi piccoli
  hero:     '4rem',    // padding verticale schermate "moment"
} as const;

// Radii — generosi, nessun angolo vivo. Sembra ceramica.
export const radius = {
  sm: '0.5rem',
  md: '0.875rem',
  lg: '1.25rem',
  xl: '1.75rem',
  '2xl': '2.25rem',
  pill: '9999px',
} as const;

// Shadows — caldi, mai grigio puro. Day usa terracotta-tinted, night usa nero profondo.
export const shadow = {
  soft:  '0 1px 2px rgba(176, 95, 45, 0.06), 0 4px 12px rgba(176, 95, 45, 0.06)',
  warm:  '0 8px 24px -8px rgba(176, 95, 45, 0.18), 0 2px 6px rgba(176, 95, 45, 0.10)',
  deep:  '0 24px 48px -16px rgba(15, 27, 45, 0.28), 0 4px 12px rgba(15, 27, 45, 0.10)',
  inset: 'inset 0 1px 2px rgba(42, 42, 42, 0.06)',
} as const;

// Animation curves — vita, non robotico.
export const motion = {
  // EaseOut con leggero overshoot, sembra una foglia che si posa.
  spring:   'cubic-bezier(0.22, 1, 0.36, 1)',
  // Slow-in, slow-out — per transizioni di stato.
  breathe:  'cubic-bezier(0.45, 0, 0.55, 1)',
  // Snap deciso — per tap response.
  snap:     'cubic-bezier(0.4, 0.0, 0.2, 1)',
  duration: {
    instant: '120ms',
    quick:   '180ms',
    normal:  '260ms',
    slow:    '420ms',
    settle:  '640ms',
  },
} as const;

// Z-index plan — niente collisioni invisibili.
export const z = {
  base:    0,
  raised:  10,
  sticky:  20,
  drawer:  40,
  overlay: 50,
  modal:   60,
  toast:   70,
  tooltip: 80,
} as const;

// Breakpoints — pensati per i superfici reali del progetto.
// mobile = phone, tablet = mobile landscape / 8" wall, desktop = laptop, wall = 21"+ kiosk.
export const breakpoints = {
  sm:  '480px',  // phone large
  md:  '768px',  // tablet portrait
  lg:  '1024px', // tablet landscape / wall 8"
  xl:  '1280px', // desktop
  '2xl': '1536px', // wall 21"+
} as const;
