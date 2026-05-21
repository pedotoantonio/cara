/**
 * Admin client for /api/v1/admin/users — family member CRUD.
 * Email and password are intentionally NOT editable from here
 * (they require dedicated flows).
 */

import { authFetch } from './auth';

const API = '/api/v1/admin/users';

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  role: string;
  birth_date: string | null;
  is_admin: boolean;
  is_active: boolean;
  wall_visible: boolean;
  wall_color: string | null;
  wall_emoji: string | null;
  created_at: string;
}

export interface UserPatch {
  full_name?: string | null;
  role?: string | null;
  birth_date?: string | null;
  is_active?: boolean;
  wall_visible?: boolean;
  wall_color?: string | null;
  wall_emoji?: string | null;
}

export async function listUsers(): Promise<User[]> {
  const r = await authFetch(API);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function updateUser(id: number, patch: UserPatch): Promise<User> {
  const r = await authFetch(`${API}/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
