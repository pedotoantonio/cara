import { apiGet } from './client';

export interface WalletWidget {
  id: string;
  kind: string;
  title?: string;
  data?: Record<string, unknown> | null;
  error?: string | null;
}

export type Surface = 'wall' | 'mobile' | 'desktop' | 'watch' | 'tv';

export interface WalletLayoutOut {
  surface: Surface;
  widget_ids: string[];
  preset?: string | null;
}

export interface WalletPreset {
  slug: string;
  name: string;
  description?: string;
  widget_ids: string[];
}

export async function getLayout(surface: Surface): Promise<WalletLayoutOut> {
  try {
    return await apiGet<WalletLayoutOut>(`/wallet/layout?surface=${surface}`);
  } catch {
    return { surface, widget_ids: [] };
  }
}

export async function listPresets(): Promise<WalletPreset[]> {
  try {
    return await apiGet<WalletPreset[]>('/wallet/presets');
  } catch {
    return [];
  }
}

export async function renderWidgets(ids: string[]): Promise<WalletWidget[]> {
  if (ids.length === 0) return [];
  try {
    const r = await apiGet<{ items?: WalletWidget[] } | WalletWidget[]>(
      `/widgets/render?ids=${ids.join(',')}`,
    );
    if (Array.isArray(r)) return r;
    return r.items ?? [];
  } catch {
    return [];
  }
}
