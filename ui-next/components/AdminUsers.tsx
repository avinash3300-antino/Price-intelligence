"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  Copy,
  KeyRound,
  Loader2,
  Plus,
  Search,
  ShieldCheck,
  UserX,
  X,
} from "lucide-react";
import { useToast } from "@/components/Toast";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  AdminApiError,
  adminApi,
  type AdminUser,
  type AdminUserDetail,
  type CountryMarket,
  type Permission,
  type RoleTemplate,
  type Scope,
} from "@/lib/admin";

const CATEGORY_LABEL: Record<string, string> = {
  view: "View",
  work: "Work",
  destructive: "Destructive",
  other: "Other",
};

function fmtWhen(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

function scopeLabel(scopes: Scope[], role: string): string {
  if (role === "admin") return "All markets";
  if (!scopes.length) return "None";
  const byCountry = new Map<string, string[]>();
  for (const s of scopes) {
    const cities = byCountry.get(s.country) ?? [];
    if (s.city) cities.push(s.city);
    byCountry.set(s.country, cities);
  }
  return Array.from(byCountry.entries())
    .map(([c, cities]) => (cities.length ? `${c} (${cities.length})` : `${c} (all)`))
    .join(", ");
}

export function AdminUsers({ currentUserId }: { currentUserId: number }) {
  const toast = useToast();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [templates, setTemplates] = useState<RoleTemplate[]>([]);
  const [markets, setMarkets] = useState<CountryMarket[]>([]);
  const [loading, setLoading] = useState(true);

  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");

  const [editing, setEditing] = useState<AdminUserDetail | null>(null);
  const [creating, setCreating] = useState(false);
  const [tempPassword, setTempPassword] = useState<{ email: string; password: string } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await adminApi.users({ q, role, status });
      setUsers(list);
    } catch (e) {
      toast.error(e instanceof AdminApiError ? e.message : "Could not load users.");
    }
  }, [q, role, status, toast]);

  useEffect(() => {
    (async () => {
      try {
        const [p, t, m] = await Promise.all([
          adminApi.permissions(),
          adminApi.templates(),
          adminApi.markets(),
        ]);
        setPermissions(p);
        setTemplates(t);
        setMarkets(m);
      } catch (e) {
        toast.error(e instanceof AdminApiError ? e.message : "Could not load reference data.");
      } finally {
        setLoading(false);
      }
    })();
    // Reference data never changes during a session; fetch once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Debounced so typing in the search box doesn't fire a request per keystroke.
  useEffect(() => {
    const t = window.setTimeout(refresh, 220);
    return () => window.clearTimeout(t);
  }, [refresh]);

  async function openUser(id: number) {
    try {
      setEditing(await adminApi.user(id));
    } catch (e) {
      toast.error(e instanceof AdminApiError ? e.message : "Could not open that user.");
    }
  }

  const counts = useMemo(
    () => ({
      total: users.length,
      admins: users.filter((u) => u.role === "admin").length,
      inactive: users.filter((u) => !u.is_active).length,
    }),
    [users],
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[13px] text-[#667085] py-20 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading…
      </div>
    );
  }

  return (
    <>
      <div className="flex items-end justify-between gap-4 flex-wrap mb-5">
        <div>
          <h1 className="text-[24px] font-bold tracking-[-0.02em] text-[#101828]">Users</h1>
          <p className="text-[13px] text-[#667085] mt-1 tnum">
            {counts.total} account{counts.total === 1 ? "" : "s"} · {counts.admins} admin
            {counts.admins === 1 ? "" : "s"}
            {counts.inactive > 0 && ` · ${counts.inactive} deactivated`}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-[9px] text-[13px] font-semibold bg-[#EA580C] text-white hover:bg-[#C2410C] transition-colors"
        >
          <Plus className="w-4 h-4" />
          Add user
        </button>
      </div>

      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="relative flex-1 min-w-[240px] max-w-[380px]">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-[#98A2B3]" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name or email"
            className="w-full pl-9 pr-3 py-2 text-[12.5px] bg-white border border-[#D0D5DD] rounded-[9px] outline-none focus:border-[#EA580C] focus:ring-2 focus:ring-[#FFEDD5] transition"
          />
        </div>
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="py-2 pl-3 pr-8 text-[12.5px] bg-white border border-[#D0D5DD] rounded-[9px] outline-none focus:border-[#EA580C] transition cursor-pointer"
        >
          <option value="">All roles</option>
          <option value="admin">Admins</option>
          <option value="user">Users</option>
        </select>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="py-2 pl-3 pr-8 text-[12.5px] bg-white border border-[#D0D5DD] rounded-[9px] outline-none focus:border-[#EA580C] transition cursor-pointer"
        >
          <option value="">Active and deactivated</option>
          <option value="active">Active only</option>
          <option value="inactive">Deactivated only</option>
        </select>
      </div>

      <div className="bg-white border border-[#E4E7EC] rounded-[12px] overflow-hidden">
        <table className="w-full text-[12.5px]">
          <thead>
            <tr className="bg-[#F9FAFB] text-[#98A2B3] text-[10.5px] uppercase tracking-[0.06em]">
              <th className="text-left px-4 py-2.5 font-semibold">Person</th>
              <th className="text-left px-4 py-2.5 font-semibold">Role</th>
              <th className="text-left px-4 py-2.5 font-semibold">Template</th>
              <th className="text-left px-4 py-2.5 font-semibold">Markets</th>
              <th className="text-right px-4 py-2.5 font-semibold">Perms</th>
              <th className="text-left px-4 py-2.5 font-semibold">Last sign-in</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F2F4F7]">
            {users.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-14 text-center text-[#98A2B3]">
                  No users match this filter.
                </td>
              </tr>
            )}
            {users.map((u) => (
              <tr
                key={u.id}
                onClick={() => openUser(u.id)}
                className={`cursor-pointer hover:bg-[#F9FAFB] transition-colors ${
                  u.is_active ? "" : "opacity-55"
                }`}
              >
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-[#101828]">{u.full_name}</span>
                    {u.is_owner && (
                      <span className="text-[9.5px] font-semibold uppercase tracking-[0.06em] bg-[#FFF4ED] text-[#C2410C] border border-[#FED7AA] px-[6px] py-[1px] rounded-full">
                        Owner
                      </span>
                    )}
                    {!u.is_active && (
                      <span className="text-[9.5px] font-semibold uppercase tracking-[0.06em] bg-[#F2F4F7] text-[#667085] border border-[#E4E7EC] px-[6px] py-[1px] rounded-full">
                        Deactivated
                      </span>
                    )}
                    {u.must_change_password && u.is_active && (
                      <span
                        title="Has not set their own password yet"
                        className="text-[9.5px] font-semibold uppercase tracking-[0.06em] bg-[#FFFAEB] text-[#B54708] border border-[#FEDF89] px-[6px] py-[1px] rounded-full"
                      >
                        Temp password
                      </span>
                    )}
                  </div>
                  <div className="text-[11.5px] text-[#667085] mt-0.5">{u.email}</div>
                </td>
                <td className="px-4 py-3">
                  <span
                    className="inline-flex items-center gap-1 px-2 py-[2px] rounded-full text-[10.5px] font-semibold border"
                    style={
                      u.role === "admin"
                        ? { color: "#92400E", background: "#FFFAEB", borderColor: "#FEDF89" }
                        : { color: "#475467", background: "#F2F4F7", borderColor: "#E4E7EC" }
                    }
                  >
                    <ShieldCheck className="w-3 h-3" />
                    {u.role}
                  </span>
                </td>
                <td className="px-4 py-3 text-[#344054]">{u.template_name ?? "—"}</td>
                <td className="px-4 py-3 text-[#344054]">
                  {u.role === "admin" ? (
                    <span className="text-[#98A2B3]">All markets</span>
                  ) : u.scope_count === 0 ? (
                    <span className="text-[#B42318] font-semibold">None assigned</span>
                  ) : (
                    <span className="tnum">
                      {u.scope_count} scope{u.scope_count === 1 ? "" : "s"}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-right tnum text-[#344054]">
                  {u.permission_count}
                </td>
                <td className="px-4 py-3 text-[#667085] tnum">{fmtWhen(u.last_login_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing && (
        <UserDrawer
          user={editing}
          permissions={permissions}
          templates={templates}
          markets={markets}
          currentUserId={currentUserId}
          onClose={() => setEditing(null)}
          onChanged={(u) => {
            setEditing(u);
            refresh();
          }}
          onTempPassword={setTempPassword}
        />
      )}

      {creating && (
        <CreateUserModal
          permissions={permissions}
          templates={templates}
          markets={markets}
          onClose={() => setCreating(false)}
          onCreated={(email, password) => {
            setCreating(false);
            setTempPassword({ email, password });
            refresh();
          }}
        />
      )}

      {tempPassword && (
        <TempPasswordDialog
          email={tempPassword.email}
          password={tempPassword.password}
          onClose={() => setTempPassword(null)}
        />
      )}
    </>
  );
}

/* ------------------------------------------------------------------ drawer */

function UserDrawer({
  user,
  permissions,
  templates,
  markets,
  currentUserId,
  onClose,
  onChanged,
  onTempPassword,
}: {
  user: AdminUserDetail;
  permissions: Permission[];
  templates: RoleTemplate[];
  markets: CountryMarket[];
  currentUserId: number;
  onClose: () => void;
  onChanged: (u: AdminUserDetail) => void;
  onTempPassword: (v: { email: string; password: string }) => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<null | "deactivate" | "reset">(null);

  const template = templates.find((t) => t.id === user.role_template_id) ?? null;
  const templatePerms = new Set(template?.permissions ?? []);
  const isSelf = user.id === currentUserId;

  async function run<T>(fn: () => Promise<T>, okMessage: string) {
    setBusy(true);
    try {
      const result = await fn();
      toast.success(okMessage);
      return result;
    } catch (e) {
      toast.error(e instanceof AdminApiError ? e.message : "Something went wrong.");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function togglePermission(key: string) {
    // The stored value is an override relative to the template. Ticking a box
    // the template already grants simply removes the override rather than
    // writing a redundant one.
    const held = user.effective_permissions.includes(key);
    const next = { ...user.overrides };
    const fromTemplate = templatePerms.has(key);
    if (held === fromTemplate) {
      next[key] = !held;          // diverge from the template
    } else {
      delete next[key];           // back in line with it
    }
    const updated = await run(
      () => adminApi.setPermissions(user.id, next),
      "Permissions updated",
    );
    if (updated) onChanged(updated);
  }

  async function toggleScope(country: string, city: string | null) {
    const exists = user.scopes.some((s) => s.country === country && s.city === city);
    let next = exists
      ? user.scopes.filter((s) => !(s.country === country && s.city === city))
      : [...user.scopes, { country, city }];
    // Granting a whole country supersedes its individual cities; keeping both
    // would be redundant and read as if the cities were a further restriction.
    if (!exists && city === null) {
      next = next.filter((s) => s.country !== country || s.city === null);
    }
    const updated = await run(() => adminApi.setScopes(user.id, next), "Markets updated");
    if (updated) onChanged(updated);
  }

  const byCategory = useMemo(() => {
    const groups = new Map<string, Permission[]>();
    for (const p of permissions) {
      const arr = groups.get(p.category) ?? [];
      arr.push(p);
      groups.set(p.category, arr);
    }
    return Array.from(groups.entries());
  }, [permissions]);

  return (
    <div className="fixed inset-0 z-[90] flex justify-end bg-black/35 backdrop-blur-[2px]" onClick={onClose}>
      <aside
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Edit ${user.email}`}
        className="w-full max-w-[560px] h-full bg-white shadow-2xl flex flex-col"
      >
        <header className="px-5 py-4 border-b border-[#E4E7EC] flex items-start justify-between gap-3 shrink-0">
          <div className="min-w-0">
            <div className="text-[16px] font-bold text-[#101828] truncate">{user.full_name}</div>
            <div className="text-[12px] text-[#667085] truncate">{user.email}</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="p-1.5 rounded-[8px] text-[#98A2B3] hover:text-[#101828] hover:bg-[#F2F4F7] transition shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-5 space-y-6">
          {user.is_owner && (
            <div className="border border-[#FED7AA] bg-[#FFF4ED] rounded-[10px] px-4 py-3 text-[12.5px] text-[#7A2E0E] leading-relaxed">
              <span className="font-semibold">Owner account.</span> Its role and
              status are locked so the system can never be locked out of itself.
            </div>
          )}

          <section>
            <SectionLabel>Account</SectionLabel>
            <div className="space-y-3">
              <Row label="Role">
                <select
                  disabled={busy || user.is_owner || isSelf}
                  value={user.role}
                  onChange={async (e) => {
                    const updated = await run(
                      () => adminApi.updateUser(user.id, { role: e.target.value }),
                      "Role updated",
                    );
                    if (updated) onChanged(updated);
                  }}
                  className="py-1.5 pl-2.5 pr-8 text-[12.5px] bg-white border border-[#D0D5DD] rounded-[8px] outline-none focus:border-[#EA580C] disabled:bg-[#F9FAFB] disabled:text-[#98A2B3] cursor-pointer"
                >
                  <option value="user">user</option>
                  <option value="admin">admin</option>
                </select>
              </Row>
              <Row label="Template">
                <select
                  disabled={busy}
                  value={user.role_template_id ?? ""}
                  onChange={async (e) => {
                    const v = e.target.value ? Number(e.target.value) : null;
                    const updated = await run(
                      () => adminApi.updateUser(user.id, { role_template_id: v }),
                      "Template updated",
                    );
                    if (updated) onChanged(updated);
                  }}
                  className="py-1.5 pl-2.5 pr-8 text-[12.5px] bg-white border border-[#D0D5DD] rounded-[8px] outline-none focus:border-[#EA580C] cursor-pointer"
                >
                  <option value="">No template</option>
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </Row>
              <Row label="Status">
                <span className={user.is_active ? "text-[#067647] font-semibold" : "text-[#B42318] font-semibold"}>
                  {user.is_active ? "Active" : "Deactivated"}
                </span>
              </Row>
              <Row label="Last sign-in">
                <span className="tnum text-[#344054]">{fmtWhen(user.last_login_at)}</span>
              </Row>
            </div>
          </section>

          <section>
            <SectionLabel>
              Permissions — {user.effective_permissions.length} of {permissions.length}
            </SectionLabel>
            {user.role === "admin" ? (
              <div className="border border-dashed border-[#D0D5DD] rounded-[10px] px-4 py-5 text-[12.5px] text-[#667085]">
                Administrators hold every permission and are not restricted by
                markets. Change the role to grant permissions individually.
              </div>
            ) : (
              <div className="space-y-4">
                {byCategory.map(([category, perms]) => (
                  <div key={category}>
                    <div className="text-[11px] font-semibold text-[#667085] mb-1.5">
                      {CATEGORY_LABEL[category] ?? category}
                    </div>
                    <div className="border border-[#E4E7EC] rounded-[10px] divide-y divide-[#F2F4F7] overflow-hidden">
                      {perms.map((p) => {
                        const held = user.effective_permissions.includes(p.key);
                        const overridden = p.key in user.overrides;
                        return (
                          <label
                            key={p.key}
                            className="flex items-start gap-2.5 px-3.5 py-2.5 hover:bg-[#F9FAFB] cursor-pointer transition"
                          >
                            <input
                              type="checkbox"
                              checked={held}
                              disabled={busy}
                              onChange={() => togglePermission(p.key)}
                              className="mt-[3px] accent-[#EA580C] w-3.5 h-3.5"
                            />
                            <span className="min-w-0">
                              <span className="text-[12.5px] font-medium text-[#101828]">
                                {p.label}
                              </span>
                              {overridden && (
                                <span className="ml-1.5 text-[9.5px] font-semibold uppercase tracking-[0.06em] bg-[#FFF4ED] text-[#C2410C] border border-[#FED7AA] px-[5px] py-[1px] rounded-full">
                                  override
                                </span>
                              )}
                              <span className="block text-[11px] text-[#667085] leading-snug mt-0.5">
                                {p.description}
                              </span>
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ))}
                <p className="text-[11px] text-[#98A2B3] leading-relaxed">
                  Ticks that differ from the <b>{template?.name ?? "template"}</b> are
                  saved as overrides. Matching the template again removes the override.
                </p>
              </div>
            )}
          </section>

          <section>
            <SectionLabel>Markets — {scopeLabel(user.scopes, user.role)}</SectionLabel>
            {user.role === "admin" ? (
              <div className="border border-dashed border-[#D0D5DD] rounded-[10px] px-4 py-5 text-[12.5px] text-[#667085]">
                Administrators see every market.
              </div>
            ) : (
              <>
                {user.scopes.length === 0 && (
                  <div className="mb-2.5 border border-[#FECACA] bg-[#FEF2F2] rounded-[10px] px-3.5 py-2.5 text-[12px] text-[#7A271A]">
                    No markets assigned — this user currently sees nothing at all.
                  </div>
                )}
                <div className="border border-[#E4E7EC] rounded-[10px] divide-y divide-[#F2F4F7] max-h-[320px] overflow-y-auto">
                  {markets.map((m) => {
                    const wholeCountry = user.scopes.some(
                      (s) => s.country === m.country && s.city === null,
                    );
                    return (
                      <div key={m.country} className="px-3.5 py-2.5">
                        <label className="flex items-center gap-2.5 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={wholeCountry}
                            disabled={busy}
                            onChange={() => toggleScope(m.country, null)}
                            className="accent-[#EA580C] w-3.5 h-3.5"
                          />
                          <span className="text-[12.5px] font-semibold text-[#101828]">
                            {m.country}
                          </span>
                          <span className="text-[11px] text-[#98A2B3] tnum">
                            {m.products} products · all cities
                          </span>
                        </label>
                        {!wholeCountry && m.cities.length > 0 && (
                          <div className="mt-1.5 ml-6 flex flex-wrap gap-1.5">
                            {m.cities.map((city) => {
                              const on = user.scopes.some(
                                (s) => s.country === m.country && s.city === city.city,
                              );
                              return (
                                <button
                                  key={city.city}
                                  type="button"
                                  disabled={busy}
                                  onClick={() => toggleScope(m.country, city.city)}
                                  className={`inline-flex items-center gap-1 px-2 py-[3px] rounded-full text-[11px] font-medium border transition ${
                                    on
                                      ? "bg-[#FFF4ED] border-[#FED7AA] text-[#C2410C]"
                                      : "bg-white border-[#E4E7EC] text-[#667085] hover:border-[#D0D5DD]"
                                  }`}
                                >
                                  {on && <Check className="w-3 h-3" />}
                                  {city.city}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </section>
        </div>

        <footer className="px-5 py-3.5 border-t border-[#E4E7EC] flex items-center gap-2 shrink-0">
          <button
            type="button"
            disabled={busy}
            onClick={() => setConfirm("reset")}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-[8px] text-[12.5px] font-semibold border border-[#D0D5DD] text-[#344054] hover:border-[#EA580C] hover:text-[#EA580C] transition disabled:opacity-50"
          >
            <KeyRound className="w-3.5 h-3.5" />
            Reset password
          </button>
          {user.is_active && !user.is_owner && !isSelf && (
            <button
              type="button"
              disabled={busy}
              onClick={() => setConfirm("deactivate")}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-[8px] text-[12.5px] font-semibold border border-[#FECACA] text-[#B42318] hover:bg-[#FEF2F2] transition disabled:opacity-50"
            >
              <UserX className="w-3.5 h-3.5" />
              Deactivate
            </button>
          )}
          {!user.is_active && (
            <button
              type="button"
              disabled={busy}
              onClick={async () => {
                const updated = await run(
                  () => adminApi.updateUser(user.id, { is_active: true }),
                  "Account reactivated",
                );
                if (updated) onChanged(updated);
              }}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-[8px] text-[12.5px] font-semibold border border-[#D0D5DD] text-[#344054] hover:border-[#067647] hover:text-[#067647] transition disabled:opacity-50"
            >
              Reactivate
            </button>
          )}
          {busy && <Loader2 className="w-4 h-4 animate-spin text-[#98A2B3] ml-auto" />}
        </footer>
      </aside>

      {confirm === "reset" && (
        <ConfirmDialog
          open
          title="Reset this password?"
          body={`${user.email} will be signed out everywhere and given a new temporary password, which you'll need to pass on to them.`}
          confirmLabel="Reset password"
          onCancel={() => setConfirm(null)}
          onConfirm={async () => {
            setConfirm(null);
            const res = await run(() => adminApi.resetPassword(user.id), "Password reset");
            if (res) {
              onTempPassword({ email: user.email, password: res.temporary_password });
              const fresh = await adminApi.user(user.id).catch(() => null);
              if (fresh) onChanged(fresh);
            }
          }}
        />
      )}
      {confirm === "deactivate" && (
        <ConfirmDialog
          open
          danger
          title="Deactivate this account?"
          body={`${user.email} will be signed out immediately and unable to sign back in. Their mappings stay attributed to them, and you can reactivate later.`}
          confirmLabel="Deactivate"
          onCancel={() => setConfirm(null)}
          onConfirm={async () => {
            setConfirm(null);
            const ok = await run(() => adminApi.deactivate(user.id), "Account deactivated");
            if (ok !== null) {
              const fresh = await adminApi.user(user.id).catch(() => null);
              if (fresh) onChanged(fresh);
            }
          }}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------ create modal */

function CreateUserModal({
  permissions,
  templates,
  markets,
  onClose,
  onCreated,
}: {
  permissions: Permission[];
  templates: RoleTemplate[];
  markets: CountryMarket[];
  onClose: () => void;
  onCreated: (email: string, password: string) => void;
}) {
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState("user");
  const [templateId, setTemplateId] = useState<number | null>(
    templates.find((t) => t.name === "Analyst")?.id ?? null,
  );
  const [scopes, setScopes] = useState<Scope[]>([]);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await adminApi.createUser({
        email: email.trim(),
        full_name: fullName.trim(),
        role,
        role_template_id: templateId,
        scopes,
        overrides: {},
      });
      toast.success(`${res.email} created`);
      onCreated(res.email, res.temporary_password);
    } catch (err) {
      toast.error(err instanceof AdminApiError ? err.message : "Could not create the user.");
      setBusy(false);
    }
  }

  const field =
    "w-full px-3 py-2 text-[13px] bg-white border border-[#D0D5DD] rounded-[9px] outline-none focus:border-[#EA580C] focus:ring-2 focus:ring-[#FFEDD5] transition";
  const label = "block text-[12px] font-semibold text-[#344054] mb-1.5";

  return (
    <div className="fixed inset-0 z-[95] bg-black/40 backdrop-blur-[2px] flex items-start justify-center pt-14 px-4 overflow-y-auto" onClick={onClose}>
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[520px] bg-white rounded-[14px] border border-[#E4E7EC] shadow-2xl overflow-hidden mb-14"
      >
        <div className="px-5 py-4 border-b border-[#F2F4F7] flex items-center justify-between">
          <div className="text-[15px] font-semibold text-[#101828]">Add user</div>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 text-[#98A2B3] hover:text-[#101828]">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3.5">
          <div>
            <label htmlFor="cu-name" className={label}>Full name</label>
            <input id="cu-name" required value={fullName} onChange={(e) => setFullName(e.target.value)} className={field} />
          </div>
          <div>
            <label htmlFor="cu-email" className={label}>Email</label>
            <input id="cu-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@raynatours.com" className={field} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="cu-role" className={label}>Role</label>
              <select id="cu-role" value={role} onChange={(e) => setRole(e.target.value)} className={field}>
                <option value="user">user</option>
                <option value="admin">admin</option>
              </select>
            </div>
            <div>
              <label htmlFor="cu-tpl" className={label}>Template</label>
              <select
                id="cu-tpl"
                value={templateId ?? ""}
                onChange={(e) => setTemplateId(e.target.value ? Number(e.target.value) : null)}
                className={field}
              >
                <option value="">No template</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
          </div>

          {role === "user" && (
            <div>
              <label className={label}>Markets</label>
              <div className="border border-[#E4E7EC] rounded-[9px] max-h-[200px] overflow-y-auto divide-y divide-[#F2F4F7]">
                {markets.map((m) => {
                  const on = scopes.some((s) => s.country === m.country && s.city === null);
                  return (
                    <label key={m.country} className="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-[#F9FAFB]">
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() =>
                          setScopes((xs) =>
                            on
                              ? xs.filter((s) => s.country !== m.country)
                              : [...xs, { country: m.country, city: null }],
                          )
                        }
                        className="accent-[#EA580C] w-3.5 h-3.5"
                      />
                      <span className="text-[12.5px] text-[#101828]">{m.country}</span>
                      <span className="text-[11px] text-[#98A2B3] tnum ml-auto">{m.products}</span>
                    </label>
                  );
                })}
              </div>
              <p className="text-[11px] text-[#98A2B3] mt-1.5">
                Whole countries here; narrow to specific cities after creating them.
                No markets means they see nothing.
              </p>
            </div>
          )}
        </div>

        <div className="px-5 py-3.5 border-t border-[#F2F4F7] flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3.5 py-2 rounded-[8px] text-[12.5px] font-semibold text-[#475467] hover:bg-[#F2F4F7] transition">
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-[8px] text-[12.5px] font-semibold bg-[#EA580C] text-white hover:bg-[#C2410C] disabled:opacity-60 transition"
          >
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
            Create user
          </button>
        </div>
      </form>
    </div>
  );
}

/* --------------------------------------------------------- temp password */

function TempPasswordDialog({
  email,
  password,
  onClose,
}: {
  email: string;
  password: string;
  onClose: () => void;
}) {
  const toast = useToast();
  return (
    <div className="fixed inset-0 z-[100] bg-black/40 backdrop-blur-[2px] flex items-center justify-center px-4">
      <div className="w-full max-w-[440px] bg-white rounded-[14px] border border-[#E4E7EC] shadow-2xl overflow-hidden">
        <div className="px-5 py-4 border-b border-[#F2F4F7] text-[15px] font-semibold text-[#101828]">
          Temporary password
        </div>
        <div className="px-5 py-4">
          <p className="text-[12.5px] text-[#475467] leading-relaxed mb-3">
            Pass this to <span className="font-semibold text-[#101828]">{email}</span>.
            They&rsquo;ll be asked to set their own on first sign-in. It is stored
            only as a hash, so this is the one time it can be shown.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2.5 bg-[#F9FAFB] border border-[#E4E7EC] rounded-[9px] text-[13.5px] font-mono text-[#101828] select-all break-all">
              {password}
            </code>
            <button
              type="button"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(password);
                  toast.success("Copied to clipboard");
                } catch {
                  toast.error("Could not copy — select it and copy manually.");
                }
              }}
              className="p-2.5 rounded-[9px] border border-[#D0D5DD] text-[#475467] hover:border-[#EA580C] hover:text-[#EA580C] transition shrink-0"
              aria-label="Copy password"
            >
              <Copy className="w-4 h-4" />
            </button>
          </div>
        </div>
        <div className="px-5 py-3.5 border-t border-[#F2F4F7] flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-[8px] text-[12.5px] font-semibold bg-[#EA580C] text-white hover:bg-[#C2410C] transition"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ bits */

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-[#98A2B3] mb-2">
      {children}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-[12.5px] text-[#667085]">{label}</span>
      {children}
    </div>
  );
}
