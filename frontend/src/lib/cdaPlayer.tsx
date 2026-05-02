/**
 * Global content player — single instance mounted at app root.
 *
 * Any code can call `useCdaPlayer().open(content)` to display a
 * `<MediaPlayer>` (audio / video / image / document) or `<ArticleReader>`
 * depending on the kind. Replaces the older `RadioPlayerProvider` for
 * everything except the legacy `<RadioMiniBar>` bar (kept for now).
 */

import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';

import type { CdaKind } from '../api/cda';
import { ArticleReader } from '../components/ArticleReader';
import { MediaPlayer } from '../components/MediaPlayer';

export interface OpenContent {
  kind: CdaKind;
  url: string;
  title: string | null;
  source_domain: string | null;
  metadata: Record<string, unknown>;
  content_id: string;
}

interface CdaPlayerCtx {
  open: (content: OpenContent) => void;
  close: () => void;
}

const Ctx = createContext<CdaPlayerCtx | null>(null);

export function CdaPlayerProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<OpenContent | null>(null);
  const open = useCallback((c: OpenContent) => setActive(c), []);
  const close = useCallback(() => setActive(null), []);
  return (
    <Ctx.Provider value={{ open, close }}>
      {children}
      {active && active.kind === 'article' ? (
        <ArticleReader content={active} onClose={close} />
      ) : null}
      {active && active.kind !== 'article' ? (
        <MediaPlayer content={active} onClose={close} />
      ) : null}
    </Ctx.Provider>
  );
}

export function useCdaPlayer(): CdaPlayerCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useCdaPlayer must be used inside <CdaPlayerProvider>');
  return v;
}
