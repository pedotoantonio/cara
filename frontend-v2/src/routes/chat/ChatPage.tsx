import { useEffect } from 'react';
import { useAvatarStore } from '@/state/avatar';
import { Card, CardTitle, CardSubtitle } from '@/design/components';

export function ChatPage() {
  const setAvatar = useAvatarStore((s) => s.setAvatar);
  useEffect(() => {
    setAvatar({
      size: 'floating',
      energy: 'idle',
      emotion: 'neutral',
      glowAccent: 'lilac',
      caption: 'Pronta a chiacchierare',
      context: 'chat',
    });
  }, [setAvatar]);

  return (
    <div className="container-app py-6">
      <h1 className="font-display text-3xl mb-4">Chat</h1>
      <Card padding="lg">
        <CardTitle>Conversazione</CardTitle>
        <CardSubtitle>
          Qui chatti con CARA. Streaming SSE, voice in/out, workflow preview.
        </CardSubtitle>
        <p className="mt-4 text-sm text-text-muted">
          Pagina in costruzione (Milestone 3).
        </p>
      </Card>
    </div>
  );
}
