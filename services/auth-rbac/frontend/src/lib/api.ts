/**
 * api.ts — Typed wrappers for every Cloud Function endpoint
 * ===========================================================
 * Base URL: VITE_API_BASE_URL in .env.local
 *   Production : https://us-central1-simple-tort-zadroga-prod.cloudfunctions.net
 *   Emulator   : http://localhost:5001/simple-tort-zadroga-prod/us-central1
 */

import { auth } from "./firebase";

// ── Base URL ──────────────────────────────────────────────────────────────
const _apiBase = import.meta.env.VITE_API_BASE_URL;
if (!_apiBase && import.meta.env.PROD) {
  throw new Error("VITE_API_BASE_URL must be set for production builds");
}
export const API_BASE =
  _apiBase ?? "http://localhost:5001/simpletort-zadroga-dev/us-central1";



// ── Role types (mirrors backend rbac.py) ─────────────────────────────────
export type BackendRole =
  | "client"
  | "admin_staff"
  | "paralegal"
  | "junior_partner"
  | "senior_partner"
  | "system_admin";

export const BACKEND_ROLE_LABELS: Record<BackendRole, string> = {
  client:         "Client",
  system_admin:   "System Admin",
  admin_staff:    "Admin Staff",
  paralegal:      "Paralegal",
  junior_partner: "Attorney",
  senior_partner: "Senior Partner",
};

// Frontend label → backend role (for UserForm selects)
export const UI_ROLE_TO_BACKEND: Record<string, BackendRole> = {
  "Senior Partner": "senior_partner",
  "Attorney":       "junior_partner",
  "Paralegal":      "paralegal",
  "Admin Staff":    "admin_staff",
  "Client":         "client",
};

// ── Shared types ──────────────────────────────────────────────────────────
export interface ApiUser {
  userId:            string;
  email:             string;
  displayName:       string;
  role:              BackendRole;          // human-readable: "Admin Staff", "Paralegal", etc.
  isActive:          boolean;
  googleWorkspaceId: string;
  lastLoginAt:       string | null;
  createdAt:         string;
  // Computed by backend — not stored in Firestore
  activeCaseCount:   number;         // count of open cases assigned to this user
  maxCaseload:       number;         // from firmSettings.defaultMaxCaseload
}

export interface AuditLogEntry {
  event_type:    string;
  timestamp:     string;
  uid?:          string;
  role?:         string;
  target_user?:  string;
  old_role?:     string;
  new_role?:     string;
  performed_by?: string;
  target_uid?:   string;
  path?:         string;
  [key: string]: unknown;
}

// ── Internal helpers ──────────────────────────────────────────────────────
async function getBearer(): Promise<string> {
  const user = auth.currentUser;
  if (!user) throw new Error("Not authenticated");
  return user.getIdToken();
}

async function apiFetch<T>(
  fn: string,
  options: RequestInit & { params?: Record<string, string> } = {}
): Promise<T> {
  const token = await getBearer();
  const { params, ...rest } = options;

  let url = `${API_BASE}/${fn}`;
  if (params) {
    const qs = new URLSearchParams(params).toString();
    if (qs) url += `?${qs}`;
  }

  const res = await fetch(url, {
    ...rest,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Authorization:  `Bearer ${token}`,
      ...(rest.headers ?? {}),
    },
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data as { error?: string }).error ?? `HTTP ${res.status}`);
  return data as T;
}

// ═══════════════════════════════════════════════════════════════════════════
// AUTH
// ═══════════════════════════════════════════════════════════════════════════

/** POST /register_fn — public, no auth header */
export async function registerUser(payload: {
  email:         string;
  password:      string;
  display_name:  string;
  role?:         BackendRole;
  portal_token?: string;
}): Promise<{ success: boolean; uid: string }> {
  const res = await fetch(`${API_BASE}/register_fn`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error ?? "Registration failed");
  return data;
}

/** POST /create_session_fn — exchange Firebase ID token for session cookie */
export async function createSession(
  idToken: string
): Promise<{ success: boolean; session_id: string }> {
  const res = await fetch(`${API_BASE}/create_session_fn`, {
    method:      "POST",
    credentials: "include",
    headers:     { "Content-Type": "application/json" },
    body:        JSON.stringify({ id_token: idToken }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error ?? "Session creation failed");
  return data;
}

/** POST /logout_fn — revoke session + clear cookies */
export async function logoutUser(): Promise<void> {
  try {
    await apiFetch("logout_fn", { method: "POST" });
  } catch {
    // best-effort — local sign-out still proceeds
  }
}

/** POST /password_reset_fn — always resolves (silent to prevent email enumeration) */
export async function requestPasswordReset(email: string): Promise<void> {
  await fetch(`${API_BASE}/password_reset_fn`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ email }),
  });
}

/** POST /create_invite_fn — generate a portal invite link (requires MANAGE_USERS) */
export async function createInvite(
  email: string
): Promise<{ invite_link: string; token: string }> {
  return apiFetch("create_invite_fn", {
    method: "POST",
    body:   JSON.stringify({ email }),
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// USERS
// ═══════════════════════════════════════════════════════════════════════════

/** POST /create_user_fn — create a staff or client user (requires MANAGE_USERS) */
export async function createUser(payload: {
  email:        string;
  password:     string;
  display_name: string;   // backend still expects display_name on registration
  role:         BackendRole;
  portal_token?: string;
}): Promise<{ success: boolean; user: ApiUser }> {
  return apiFetch("create_user_fn", {
    method: "POST",
    body:   JSON.stringify(payload),
  });
}

/** GET /list_users_fn — paginated user list (requires MANAGE_USERS) */
export async function listUsers(opts?: {
  role?:      BackendRole;
  status?:    "active" | "inactive";
  search?:    string;
  page_size?: number;
  cursor?:    string;
}): Promise<{
  users:       ApiUser[];
  has_more:    boolean;
  next_cursor: string | null;
}> {
  const params: Record<string, string> = {};
  if (opts?.role)      params.role      = opts.role;   // human-readable role string
  if (opts?.status)    params.status    = opts.status;
  if (opts?.search)    params.search    = opts.search;
  if (opts?.page_size) params.page_size = String(opts.page_size);
  if (opts?.cursor)    params.cursor    = opts.cursor;

  return apiFetch("list_users_fn", { method: "GET", params });
}

/** GET /get_user_fn?uid=xxx */
export async function getUser(uid: string): Promise<{ user: ApiUser }> {
  return apiFetch("get_user_fn", { method: "GET", params: { uid } });
}

/** PUT /update_user_fn */
export async function updateUser(payload: {
  uid:                string;
  displayName?:       string;
  role?:              string;
  isActive?:          boolean;
  googleWorkspaceId?: string;
}): Promise<{ success: boolean; updated_fields: string[] }> {
  return apiFetch("update_user_fn", {
    method: "PUT",
    body:   JSON.stringify(payload),
  });
}

/** DELETE /delete_user_fn?uid=xxx (soft-delete, requires MANAGE_USERS) */
export async function deleteUser(
  uid: string
): Promise<{ success: boolean; message: string }> {
  return apiFetch("delete_user_fn", { method: "DELETE", params: { uid } });
}

// ═══════════════════════════════════════════════════════════════════════════
// AUDIT LOG
// ═══════════════════════════════════════════════════════════════════════════

/** GET /get_audit_log_fn — requires VIEW_AUDIT_LOG (senior_partner only) */
export async function getAuditLog(opts?: {
  uid?:   string;
  limit?: number;
}): Promise<{ logs: AuditLogEntry[] }> {
  const params: Record<string, string> = {};
  if (opts?.uid)   params.uid   = opts.uid;
  if (opts?.limit) params.limit = String(opts.limit);

  return apiFetch("get_audit_log_fn", { method: "GET", params });
}
