import { useEffect } from 'react';
import { useAvatarStore } from '@/state/avatar';
import { Card, CardTitle, CardSubtitle } from '@/design/components';
import { CalendarBlank, Newspaper, MusicNote, Sun } from '@phosphor-icons/react';

const SECTIONS = [
  { label: 'Calendario', Icon: CalendarBlank, accent: 'text-accent-sky' },
  { label: 'Notizie',    Icon: Newspaper,     accent: 'text-accent-clay' },
  { label: 'Radio',      Icon: MusicNote,     accent: 'text-accent-clay' },
  { label: 'Meteo',      Icon: Sun,           accent: 'text-accent-sun' },
];

export function LifeHub() {
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'happy',
      glowAccent: 'sky',
      caption: 'La tua giornata, in un colpo d\'occhio',
      context: 'life',
    });
  }, [setAvatar]);

  return (
    <div className="container-app py-6 space-y-4">
      <h1 className="font-display text-3xl mb-4">Vita</h1>
      <div className="grid grid-cols-2 gap-3">
        {SECTIONS.map(({ label, Icon, accent }) => (
          <Card key={label} padding="lg" elevation={1}>
            <Icon size={32} weight="duotone" className={accent} />
            <CardTitle className="mt-3">{label}</CardTitle>
            <CardSubtitle>In costruzione</CardSubtitle>
          </Card>
        ))}
      </div>
    </div>
  );
}
