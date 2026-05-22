import { apiGet, apiPost } from './client';

export interface EmailProposal {
  id: number;
  user_id: number;
  source: string;
  kind: string;
  title: string;
  body: string;
  proposed_at: string;
  status: 'pending' | 'accepted' | 'rejected';
  email_subject?: string | null;
  email_from?: string | null;
}

export async function listProposals(): Promise<EmailProposal[]> {
  try {
    return await apiGet<EmailProposal[]>('/proposals');
  } catch {
    return [];
  }
}

export async function acceptProposal(id: number): Promise<void> {
  await apiPost(`/proposals/${id}/accept`, {}).catch(() => undefined);
}

export async function rejectProposal(id: number): Promise<void> {
  await apiPost(`/proposals/${id}/reject`, {}).catch(() => undefined);
}
