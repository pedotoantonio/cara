// Workflow API client.
import { authFetch } from './auth';

const API = '/api/v1/workflows';

export interface ProposedAction {
  tool: string;
  args: Record<string, unknown>;
  summary: string;
  reversible: boolean;
  signature: string;
  auto_confirmable: boolean;
  confirms_seen: number;
  confirms_remaining: number;
}

export interface WorkflowRunResponse {
  matched: boolean;
  workflow_name: string | null;
  confidence: number | null;
  reason: string | null;
  structured: Record<string, unknown> | null;
  proposed_actions: ProposedAction[];
  executed: boolean;
  execution_results: Array<Record<string, unknown>>;
}

interface RunArgs {
  text?: string;
  url?: string;
  ocr_text?: string;
  pdf_text?: string;
  image_b64?: string;
  pdf_b64?: string;
  confirmed?: boolean;
}

export async function runWorkflow(args: RunArgs): Promise<WorkflowRunResponse> {
  const r = await authFetch(`${API}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail ?? `workflow run: ${r.status}`);
  }
  return r.json();
}

/** Read a File as base64 (without data: prefix). */
export async function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== 'string') {
        reject(new Error('reader returned non-string'));
        return;
      }
      const comma = result.indexOf(',');
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error ?? new Error('read failed'));
    reader.readAsDataURL(file);
  });
}
