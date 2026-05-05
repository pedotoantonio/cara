// Wallet API client — layout per surface + presets + widget render.
import { authFetch } from './auth';

const API = '/api/v1';

export type Surface = 'wall' | 'mobile' | 'desktop' | 'watch' | 'tv';
export type WidgetSize = 'small' | 'medium' | 'large';

export interface LayoutItem {
  widget_id: string;
  size: WidgetSize;
  config: Record<string, unknown>;
}

export interface Layout {
  surface_class: Surface;
  preset: string;
  items: LayoutItem[];
  is_default: boolean;
}

export interface WalletPreset {
  slug: string;
  label: string;
  description: string;
  items: LayoutItem[];
}

export interface WidgetCatalogEntry {
  id: string;
  title: string;
  refresh_interval_s: number;
}

export interface RenderedWidget {
  widget_id: string;
  title: string;
  kind: string;
  body: Record<string, unknown>;
  deep_link: string | null;
  last_updated_unix: number | null;
  error: string | null;
}

export interface RenderResponse {
  rendered_at_unix: number;
  items: RenderedWidget[];
}

export async function getLayout(surface: Surface): Promise<Layout> {
  const r = await authFetch(`${API}/wallet/layout?surface=${surface}`);
  if (!r.ok) throw new Error(`layout failed: ${r.status}`);
  return r.json();
}

export async function putLayout(surface: Surface, items: LayoutItem[]): Promise<Layout> {
  const r = await authFetch(`${API}/wallet/layout?surface=${surface}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  });
  if (!r.ok) throw new Error(`save layout failed: ${r.status}`);
  return r.json();
}

export async function resetLayout(surface: Surface): Promise<void> {
  const r = await authFetch(`${API}/wallet/layout?surface=${surface}`, {
    method: 'DELETE',
  });
  if (!r.ok && r.status !== 204) throw new Error(`reset failed: ${r.status}`);
}

export async function listPresets(): Promise<WalletPreset[]> {
  const r = await authFetch(`${API}/wallet/presets`);
  if (!r.ok) throw new Error(`presets failed: ${r.status}`);
  return r.json();
}

export async function applyPreset(slug: string, surface: Surface): Promise<Layout> {
  const r = await authFetch(
    `${API}/wallet/preset/${encodeURIComponent(slug)}?surface=${surface}`,
    { method: 'POST' },
  );
  if (!r.ok) throw new Error(`apply preset failed: ${r.status}`);
  return r.json();
}

export async function listWidgetCatalog(): Promise<WidgetCatalogEntry[]> {
  const r = await authFetch(`${API}/widgets`);
  if (!r.ok) throw new Error(`catalog failed: ${r.status}`);
  const j = await r.json();
  return j.widgets ?? [];
}

export async function renderWidgets(
  ids: string[],
  surface: Surface = 'mobile',
  size: WidgetSize = 'medium',
): Promise<RenderResponse> {
  const idsParam = ids.join(',');
  const r = await authFetch(
    `${API}/widgets/render?ids=${encodeURIComponent(idsParam)}&surface=${surface}&size=${size}`,
  );
  if (!r.ok) throw new Error(`render failed: ${r.status}`);
  return r.json();
}
