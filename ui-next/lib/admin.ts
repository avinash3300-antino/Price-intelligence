/**
 * Admin API client.
 *
 * All calls are same-origin (nginx in production, the Next rewrite in
 * development) so the httpOnly session cookie rides along automatically.
 */

export interface Permission {
  key: string;
  label: string;
  category: string;
  description: string;
  sort_order: number;
}

export interface RoleTemplate {
  id: number;
  name: string;
  description: string;
  is_system: boolean;
  permissions: string[];
}

export interface CityMarket {
  city: string;
  products: number;
}

export interface CountryMarket {
  country: string;
  products: number;
  cities: CityMarket[];
}

export interface Scope {
  country: string;
  city: string | null;
}

export interface AdminUser {
  id: number;
  email: string;
  full_name: string;
  role: "admin" | "user";
  is_active: boolean;
  is_owner: boolean;
  must_change_password: boolean;
  template_name: string | null;
  permission_count: number;
  scope_count: number;
  created_at: string;
  last_login_at: string | null;
}

export interface AdminUserDetail extends AdminUser {
  role_template_id: number | null;
  effective_permissions: string[];
  overrides: Record<string, boolean>;
  scopes: Scope[];
}

export interface AuditEntry {
  id: number;
  actor_email: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  ip: string | null;
  created_at: string;
  before_json: unknown;
  after_json: unknown;
}

/** Surfaces the API's own message so the UI can show it verbatim in a toast. */
export class AdminApiError extends Error {}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    credentials: "include",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!r.ok) {
    let detail = `Request failed (${r.status})`;
    try {
      const body = await r.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new AdminApiError(detail);
  }
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

export const adminApi = {
  permissions: () => call<Permission[]>("/api/admin/permissions"),
  templates: () => call<RoleTemplate[]>("/api/admin/templates"),
  markets: () => call<CountryMarket[]>("/api/admin/markets"),

  users: (params: { q?: string; role?: string; status?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.q) qs.set("q", params.q);
    if (params.role) qs.set("role", params.role);
    if (params.status) qs.set("status", params.status);
    const s = qs.toString();
    return call<AdminUser[]>(`/api/admin/users${s ? `?${s}` : ""}`);
  },
  user: (id: number) => call<AdminUserDetail>(`/api/admin/users/${id}`),

  createUser: (body: {
    email: string;
    full_name: string;
    role: string;
    role_template_id: number | null;
    password?: string;
    scopes: Scope[];
    overrides: Record<string, boolean>;
  }) =>
    call<{ id: number; email: string; temporary_password: string }>(
      "/api/admin/users",
      { method: "POST", body: JSON.stringify(body) },
    ),

  updateUser: (
    id: number,
    body: Partial<{
      full_name: string;
      role: string;
      is_active: boolean;
      role_template_id: number | null;
    }>,
  ) =>
    call<AdminUserDetail>(`/api/admin/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  setPermissions: (id: number, overrides: Record<string, boolean>) =>
    call<AdminUserDetail>(`/api/admin/users/${id}/permissions`, {
      method: "PUT",
      body: JSON.stringify(overrides),
    }),

  setScopes: (id: number, scopes: Scope[]) =>
    call<AdminUserDetail>(`/api/admin/users/${id}/scopes`, {
      method: "PUT",
      body: JSON.stringify(scopes),
    }),

  resetPassword: (id: number) =>
    call<{ temporary_password: string }>(
      `/api/admin/users/${id}/reset-password`,
      { method: "POST" },
    ),

  deactivate: (id: number) =>
    call<void>(`/api/admin/users/${id}`, { method: "DELETE" }),

  audit: (params: { limit?: number; actor?: string; action?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.limit) qs.set("limit", String(params.limit));
    if (params.actor) qs.set("actor", params.actor);
    if (params.action) qs.set("action", params.action);
    const s = qs.toString();
    return call<AuditEntry[]>(`/api/admin/audit${s ? `?${s}` : ""}`);
  },
};
