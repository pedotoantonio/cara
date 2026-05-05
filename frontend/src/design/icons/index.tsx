// Custom CARA icon set — soft, hand-drawn feel.
// Tutti gli SVG sono 24×24, stroke 1.6, currentColor.
// Disegnati per somigliare a oggetti di casa (mai geometrici puri).

import type { SVGProps } from 'react';

const baseProps = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};

// ──────────────────────────────── Navigation (8) ──

const Home = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M4 11.2 12 4l8 7.2V19a1.5 1.5 0 0 1-1.5 1.5H5.5A1.5 1.5 0 0 1 4 19v-7.8Z" />
    <path d="M9.5 20.5v-5h5v5" />
  </svg>
);

const Wallet = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <rect x="3.5" y="6" width="17" height="13" rx="2.5" />
    <path d="M3.5 10h17M16 14.5h2" />
    <path d="M6 6V4.5a1 1 0 0 1 1-1h10" />
  </svg>
);

const Chat = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M4 6.5a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3h-3.2L9 20.5V16.5H7a3 3 0 0 1-3-3v-7Z" />
    <circle cx="9"  cy="10" r=".7" fill="currentColor" />
    <circle cx="12" cy="10" r=".7" fill="currentColor" />
    <circle cx="15" cy="10" r=".7" fill="currentColor" />
  </svg>
);

const Family = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <circle cx="8" cy="9" r="2.5" />
    <circle cx="16" cy="9" r="2.5" />
    <path d="M3.5 19c0-2.5 2-4.5 4.5-4.5S12.5 16.5 12.5 19" />
    <path d="M11.5 19c0-2.5 2-4.5 4.5-4.5S20.5 16.5 20.5 19" />
  </svg>
);

const SmartHome = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M3.5 12 12 4.5l8.5 7.5" />
    <path d="M5.5 11.5V19a1.5 1.5 0 0 0 1.5 1.5h10a1.5 1.5 0 0 0 1.5-1.5v-7.5" />
    <circle cx="12" cy="14.5" r="1.6" />
    <path d="M12 12.9V11" />
  </svg>
);

const Profile = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <circle cx="12" cy="8" r="3.5" />
    <path d="M4.5 20c0-3.6 3.4-6 7.5-6s7.5 2.4 7.5 6" />
  </svg>
);

const Search = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m20 20-4.2-4.2" />
  </svg>
);

const Settings = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <circle cx="12" cy="12" r="2.8" />
    <path d="M12 3v2.4M12 18.6V21M3 12h2.4M18.6 12H21M5.6 5.6l1.7 1.7M16.7 16.7l1.7 1.7M18.4 5.6l-1.7 1.7M7.3 16.7l-1.7 1.7" />
  </svg>
);

// ──────────────────────────────── Routine domain (8) ──

const Task = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <rect x="4" y="4" width="16" height="16" rx="3" />
    <path d="m8 12.5 2.6 2.6L16 9.6" />
  </svg>
);

const Shopping = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M4 5.5h2.2L9 17a1.5 1.5 0 0 0 1.5 1.2h7" />
    <path d="m6.8 8.5 13-1L18 14.5H9.2" />
    <circle cx="10.5" cy="20.5" r="1.2" />
    <circle cx="17"   cy="20.5" r="1.2" />
  </svg>
);

const Note = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M5 4.5h11l3.5 3.5V19a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5V6A1.5 1.5 0 0 1 5 4.5Z" />
    <path d="M16 4.5V8.5h3.5M8 12.5h7M8 16h5" />
  </svg>
);

const Calendar = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <rect x="3.5" y="5" width="17" height="15" rx="2" />
    <path d="M3.5 10h17M8 3.5v3M16 3.5v3" />
    <circle cx="12" cy="14.5" r="1.4" fill="currentColor" />
  </svg>
);

const Habit = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M5 12a7 7 0 1 1 14 0 7 7 0 0 1-14 0Z" />
    <path d="M12 7v5l3 2" />
  </svg>
);

const Budget = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <circle cx="12" cy="12" r="8" />
    <path d="M12 7v10M9.5 9h4a1.8 1.8 0 0 1 0 3.6h-3a1.8 1.8 0 0 0 0 3.6h4.5" />
  </svg>
);

const News = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <rect x="3.5" y="5" width="13" height="14" rx="1.5" />
    <path d="M16.5 8.5h2.5a1 1 0 0 1 1 1V18a1.5 1.5 0 0 1-3 0v-9.5Z" />
    <path d="M6.5 8.5h6.5M6.5 11.5h6.5M6.5 14.5h4" />
  </svg>
);

const Radio = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <rect x="3.5" y="8" width="17" height="11" rx="2" />
    <path d="m8 8 9-3.5" />
    <circle cx="15.5" cy="13.5" r="2.2" />
    <path d="M6.5 13.5h4M6.5 16h3" />
  </svg>
);

// ──────────────────────────────── State / status (8) ──

const Mic = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <rect x="9.5" y="3.5" width="5" height="11" rx="2.5" />
    <path d="M6 11a6 6 0 0 0 12 0M12 17v3.5M9.5 20.5h5" />
  </svg>
);

const Send = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M4 12 20 4l-3.5 16-4-7Z" />
    <path d="m12.5 13 4-9" />
  </svg>
);

const Plus = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);

const Check = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="m5 12.5 4.5 4.5L19 7" />
  </svg>
);

const Close = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="m6 6 12 12M18 6 6 18" />
  </svg>
);

const Trash = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M4.5 6.5h15M9 6.5V5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5v1.5" />
    <path d="M6 6.5 7 19a1.5 1.5 0 0 0 1.5 1.5h7A1.5 1.5 0 0 0 17 19l1-12.5" />
    <path d="M10 10v7M14 10v7" />
  </svg>
);

const Spark = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M12 4v3M12 17v3M4 12h3M17 12h3M6.3 6.3l2 2M15.7 15.7l2 2M17.7 6.3l-2 2M8.3 15.7l-2 2" />
    <circle cx="12" cy="12" r="2.4" />
  </svg>
);

const Heart = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M12 19.5s-7-4.4-7-9.4A4.1 4.1 0 0 1 12 7a4.1 4.1 0 0 1 7 3.1c0 5-7 9.4-7 9.4Z" />
  </svg>
);

// ──────────────────────────────── Misc utility (5) ──

const Sun = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <circle cx="12" cy="12" r="3.6" />
    <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" />
  </svg>
);

const Moon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M19.5 14.2A8 8 0 1 1 9.8 4.5a6.5 6.5 0 0 0 9.7 9.7Z" />
  </svg>
);

const Bell = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M6 17h12l-1.5-2v-4a4.5 4.5 0 0 0-9 0v4L6 17Z" />
    <path d="M10 19a2 2 0 0 0 4 0" />
  </svg>
);

const Sparkle = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <path d="M12 4c.5 3 1.5 4 4.5 4.5-3 .5-4 1.5-4.5 4.5-.5-3-1.5-4-4.5-4.5C11 8 12 7 12 4Z" />
    <path d="M18 14c.3 1.6.8 2.1 2.4 2.4-1.6.3-2.1.8-2.4 2.4-.3-1.6-.8-2.1-2.4-2.4 1.6-.3 2.1-.8 2.4-2.4Z" />
  </svg>
);

const Mood = (p: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...p}>
    <circle cx="12" cy="12" r="8" />
    <path d="M9 14c.6.9 1.7 1.5 3 1.5s2.4-.6 3-1.5" />
    <circle cx="9.5"  cy="10" r=".8" fill="currentColor" />
    <circle cx="14.5" cy="10" r=".8" fill="currentColor" />
  </svg>
);

// ──────────────────────────────── Registry ──

export const ICON_SET = {
  home: Home,
  wallet: Wallet,
  chat: Chat,
  family: Family,
  smartHome: SmartHome,
  profile: Profile,
  search: Search,
  settings: Settings,
  task: Task,
  shopping: Shopping,
  note: Note,
  calendar: Calendar,
  habit: Habit,
  budget: Budget,
  news: News,
  radio: Radio,
  mic: Mic,
  send: Send,
  plus: Plus,
  check: Check,
  close: Close,
  trash: Trash,
  spark: Spark,
  heart: Heart,
  sun: Sun,
  moon: Moon,
  bell: Bell,
  sparkle: Sparkle,
  mood: Mood,
} as const;

export type IconName = keyof typeof ICON_SET;

interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName;
  size?: number | string;
}

export function Icon({ name, size = 24, className, ...rest }: IconProps) {
  const Cmp = ICON_SET[name];
  return (
    <Cmp
      width={size}
      height={size}
      className={className}
      aria-hidden="true"
      focusable="false"
      {...rest}
    />
  );
}
