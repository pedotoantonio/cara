/**
 * Lightweight tool-call parser for CARA's chat output.
 *
 * The 1.5B model is instructed (via system prompt) to emit lines like:
 *   [TOOL: add_task title="comprare pane"]
 * We pull these out of the assistant text, expose them to the UI as a
 * structured action list, and strip them from the user-visible content.
 */

import { discoverContent, type CdaKind } from '../api/cda';
import { whoIsHome } from '../api/family';
import { getNews, type NewsCategory } from '../api/news';
import { createNote } from '../api/notes';
import { getStation } from '../api/radio';
import { createShopping } from '../api/shopping';
import { createTask, listTasks, updateTask } from '../api/tasks';

export type ToolCall =
  | { type: 'add_task'; title: string }
  | { type: 'complete_task'; title: string }
  | { type: 'list_tasks' }
  | { type: 'add_shopping'; title: string }
  | { type: 'add_note'; title: string; body: string }
  | { type: 'get_news'; category: NewsCategory }
  | { type: 'play_radio'; station: string }
  | { type: 'stop_radio' }
  | { type: 'who_is_home' }
  | { type: 'discover'; query: string; kind: CdaKind }
  | { type: 'unknown'; raw: string };

// Match any of our known tool names. The tolerant prefix absorbs the 1.5B's
// occasional typos around "TOOL" / "TUPO" / "TU" / missing prefix.
const TOOL_LINE_RE =
  /\[\s*(?:[A-Z_]+\s*:?\s*)?(add_task|complete_task|list_tasks|add_shopping|add_note|get_news|play_radio|stop_radio|who_is_home|discover)\b\s*([^\]]*?)\]/gi;

const CDA_KINDS: ReadonlyArray<CdaKind> = [
  'audio_stream',
  'article',
  'video',
  'podcast',
  'image',
  'document',
];

const NEWS_CATEGORIES: ReadonlyArray<NewsCategory> = ['all', 'italia', 'mondo', 'economia', 'tech', 'sport'];

function parseArgs(s: string): Record<string, string> {
  // very small "key=\"value\"" parser; tolerant of unquoted values
  const out: Record<string, string> = {};
  const re = /([a-z_]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s]+))/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    out[m[1]] = m[2] ?? m[3] ?? m[4] ?? '';
  }
  return out;
}

export interface ParsedAssistantMessage {
  cleaned: string;
  toolCalls: ToolCall[];
}

export function parseToolCalls(content: string): ParsedAssistantMessage {
  // Collect every match in order, but only keep the FIRST valid tool call.
  // The 1.5B model occasionally "tool-floods" emitting several at once when
  // the user asked for a single thing; the system prompt says one per message
  // and we enforce that here defensively.
  const allCalls: ToolCall[] = [];
  const cleaned = content.replace(TOOL_LINE_RE, (_match, name: string, argstr: string) => {
    const args = parseArgs(argstr);
    const lower = name.toLowerCase();
    if (lower === 'add_task') {
      const title = args.title?.trim();
      if (title) allCalls.push({ type: 'add_task', title });
    } else if (lower === 'complete_task') {
      const title = args.title?.trim();
      if (title) allCalls.push({ type: 'complete_task', title });
    } else if (lower === 'list_tasks') {
      allCalls.push({ type: 'list_tasks' });
    } else if (lower === 'add_shopping') {
      const title = args.title?.trim();
      if (title) allCalls.push({ type: 'add_shopping', title });
    } else if (lower === 'add_note') {
      const t = args.title?.trim() ?? '';
      const b = args.body?.trim() ?? '';
      if (t || b) allCalls.push({ type: 'add_note', title: t, body: b });
    } else if (lower === 'get_news') {
      const raw = (args.category ?? '').toLowerCase();
      const cat = (NEWS_CATEGORIES.includes(raw as NewsCategory) ? raw : 'all') as NewsCategory;
      allCalls.push({ type: 'get_news', category: cat });
    } else if (lower === 'play_radio') {
      const station = (args.station ?? '').trim();
      if (station) allCalls.push({ type: 'play_radio', station });
    } else if (lower === 'stop_radio') {
      allCalls.push({ type: 'stop_radio' });
    } else if (lower === 'who_is_home') {
      allCalls.push({ type: 'who_is_home' });
    } else if (lower === 'discover') {
      const query = (args.query ?? '').trim();
      const kindRaw = (args.kind ?? 'article').toLowerCase() as CdaKind;
      const kind = CDA_KINDS.includes(kindRaw) ? kindRaw : 'article';
      if (query) allCalls.push({ type: 'discover', query, kind });
    } else {
      allCalls.push({ type: 'unknown', raw: `${name} ${argstr}` });
    }
    return ''; // strip the tool line from user-visible content
  });
  const firstValid = allCalls.find((c) => c.type !== 'unknown');
  const toolCalls = firstValid ? [firstValid] : [];
  return { cleaned: cleaned.replace(/\n{3,}/g, '\n\n').trim(), toolCalls };
}

/** Default copy when the model emits only tool lines and no actual prose. */
const TOOL_FALLBACK_BY_KIND: Partial<Record<ToolCall['type'], string>> = {
  add_task: 'Aggiunto alla tua lista 👍',
  complete_task: 'Segnata come fatta ✅',
  list_tasks: 'Ecco le tue cose da fare:',
  add_shopping: 'Messa nella spesa 🛒',
  add_note: 'Nota salvata 📝',
  get_news: 'Ecco le ultime notizie:',
  play_radio: 'Accendo la radio.',
  stop_radio: 'Spengo la radio.',
  who_is_home: 'Guardo subito chi vedo in casa…',
  discover: 'Cerco e te lo metto su…',
};

/** Pick a friendly default if `cleaned` is empty/too short after parsing. */
export function ensureSomeProse(cleaned: string, toolCalls: ToolCall[]): string {
  const trimmed = cleaned.trim();
  if (trimmed.length >= 4) return trimmed;
  if (toolCalls.length === 0) return trimmed;
  const kind = toolCalls[0].type;
  return TOOL_FALLBACK_BY_KIND[kind] ?? 'Ecco:';
}

/**
 * Strip tool markup from a string for *display* purposes — used by the
 * MessageBubble to hide `[TOOL: ...]` while the assistant is still streaming.
 *
 * Removes:
 *   - any complete `[TOOL: ...]` (and tolerant typo variants)
 *   - any trailing `[…` without a closing `]` (tool mid-emission)
 *
 * Pure, safe to call on every render. We rebuild a fresh regex to avoid the
 * stateful `lastIndex` of the global module-level one.
 */
export function stripToolsForDisplay(text: string): string {
  if (!text) return text;
  const re = new RegExp(TOOL_LINE_RE.source, 'gi');
  let out = text.replace(re, '');
  const lastOpen = out.lastIndexOf('[');
  if (lastOpen !== -1 && out.indexOf(']', lastOpen) === -1) {
    out = out.slice(0, lastOpen);
  }
  return out.replace(/\n{3,}/g, '\n\n').trimEnd();
}

export interface ExecutedTool {
  call: ToolCall;
  ok: boolean;
  detail: string;
}

function fuzzyMatch(query: string, choices: string[]): number {
  // Returns the index of the best match, or -1 if none reasonable.
  const q = query.toLowerCase().trim();
  // Prefer substring match
  let bestIdx = -1;
  let bestScore = 0;
  choices.forEach((c, i) => {
    const lc = c.toLowerCase();
    if (lc === q) {
      bestIdx = i;
      bestScore = Infinity;
      return;
    }
    if (lc.includes(q) || q.includes(lc)) {
      const score = Math.min(lc.length, q.length) / Math.max(lc.length, q.length);
      if (score > bestScore) {
        bestScore = score;
        bestIdx = i;
      }
    }
  });
  return bestIdx;
}

export interface ToolExecCtx {
  /** Optional radio control surface — required for play_radio / stop_radio. */
  radio?: {
    playStation: (s: { id: string; name: string; url: string; genre: string; country: string; description: string }) => void;
    stop: () => void;
  };
  /** Speak callback (when set, news-style tools read their digest aloud). */
  speak?: (text: string) => void;
  /** Optional callback that opens a player for arbitrary content discovered
   *  by the CDA. The bubble shows a short detail line; full playback happens
   *  in a `<MediaPlayer>` / `<ArticleReader>` mounted at app level. */
  openContent?: (content: {
    kind: CdaKind;
    url: string;
    title: string | null;
    source_domain: string | null;
    metadata: Record<string, unknown>;
    content_id: string;
  }) => void;
}

export async function executeTools(
  calls: ToolCall[],
  ctx: ToolExecCtx = {},
): Promise<ExecutedTool[]> {
  const results: ExecutedTool[] = [];
  for (const c of calls) {
    try {
      if (c.type === 'add_task') {
        const t = await createTask(c.title);
        results.push({ call: c, ok: true, detail: `aggiunto: "${t.title}"` });
      } else if (c.type === 'complete_task') {
        const all = await listTasks(false); // pending only
        const idx = fuzzyMatch(c.title, all.map((t) => t.title));
        if (idx === -1) {
          results.push({
            call: c,
            ok: false,
            detail: `nessuna task pendente con titolo "${c.title}"`,
          });
        } else {
          const updated = await updateTask(all[idx].id, { done: true });
          results.push({ call: c, ok: true, detail: `completata: "${updated.title}"` });
        }
      } else if (c.type === 'list_tasks') {
        const all = await listTasks(false);
        if (all.length === 0) {
          results.push({ call: c, ok: true, detail: 'nessuna task pendente' });
        } else {
          const list = all.map((t) => `• ${t.title}`).join('\n');
          results.push({ call: c, ok: true, detail: `${all.length} task pendenti:\n${list}` });
        }
      } else if (c.type === 'add_shopping') {
        const it = await createShopping(c.title);
        results.push({ call: c, ok: true, detail: `nella spesa: "${it.title}"` });
      } else if (c.type === 'add_note') {
        const n = await createNote(c.title || 'Nota', c.body);
        results.push({ call: c, ok: true, detail: `nota salvata: "${n.title}"` });
      } else if (c.type === 'get_news') {
        const r = await getNews(c.category, 5);
        if (r.count === 0) {
          results.push({ call: c, ok: true, detail: 'Nessuna news in questo momento.' });
        } else {
          const head = r.items
            .slice(0, 5)
            .map((it, i) => `${i + 1}. ${it.title} — ${it.source}`)
            .join('\n');
          results.push({
            call: c,
            ok: true,
            detail: `Top news (${c.category}):\n${head}`,
          });
          // Read the Italian digest aloud if a speak callback was provided.
          if (ctx.speak && r.digest) ctx.speak(r.digest);
        }
      } else if (c.type === 'play_radio') {
        try {
          const station = await getStation(c.station);
          ctx.radio?.playStation(station);
          results.push({ call: c, ok: true, detail: `In onda: ${station.name}` });
        } catch (e) {
          results.push({ call: c, ok: false, detail: (e as Error).message });
        }
      } else if (c.type === 'stop_radio') {
        ctx.radio?.stop();
        results.push({ call: c, ok: true, detail: 'Radio spenta.' });
      } else if (c.type === 'discover') {
        try {
          const r = await discoverContent(c.query, c.kind);
          ctx.openContent?.({
            kind: r.kind as CdaKind,
            url: r.url,
            title: r.title,
            source_domain: r.source_domain,
            metadata: r.metadata,
            content_id: r.content_id,
          });
          const label = r.title ?? r.url;
          const src = r.source_domain ? ` (${r.source_domain})` : '';
          results.push({
            call: c,
            ok: true,
            detail: `Trovato: ${label}${src}${r.cached ? ' · dalla memoria' : ''}`,
          });
        } catch (e) {
          results.push({ call: c, ok: false, detail: (e as Error).message });
        }
      } else if (c.type === 'who_is_home') {
        const r = await whoIsHome(15);
        if (r.count === 0) {
          results.push({ call: c, ok: true, detail: 'In questo momento non vedo nessuno in casa.' });
        } else {
          const names = r.people
            .map((p) =>
              p.minutes_ago === 0 ? `${p.name} (ora)` : `${p.name} (${p.minutes_ago} min fa)`,
            )
            .join(', ');
          results.push({
            call: c,
            ok: true,
            detail: `In casa adesso (ultimi ${r.window_minutes} min): ${names}`,
          });
        }
      } else {
        results.push({ call: c, ok: false, detail: `tool sconosciuto: ${c.raw}` });
      }
    } catch (e) {
      results.push({ call: c, ok: false, detail: (e as Error).message });
    }
  }
  return results;
}
