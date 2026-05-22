import { Card, CardSubtitle, CardTitle } from '@/design/components';
import { MusicNote } from '@phosphor-icons/react';

export function RadioPage() {
  return (
    <div className="container-app py-4">
      <Card padding="lg" surface="surface" elevation={0}>
        <div className="text-center py-6">
          <MusicNote size={32} weight="duotone" className="text-accent-clay mx-auto" />
          <CardTitle className="mt-3">Radio</CardTitle>
          <CardSubtitle className="mt-1">
            La radio streaming arriverà nella prossima versione.
          </CardSubtitle>
          <p className="mt-3 text-xs text-text-muted">
            Per ora chiedi a CARA "metti la radio" dalla chat o dal microfono.
          </p>
        </div>
      </Card>
    </div>
  );
}
