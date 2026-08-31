"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, Loader2, Search, X } from "lucide-react";
import { useToast } from "@/components/Toast";
import { AdminApiError, adminApi, type AuditEntry } from "@/lib/admin";

/** Human phrasing for each action key, so the log reads as sentences. */
const ACTION_LABEL: Record<string, string> = {
  "auth.login": "signed in",
  "auth.logout": "signed out",
  "auth.login_failed": "failed sign-in",
  "auth.password_changed": "changed their password",
  "user.created": "created a user",
  "user.updated": "updated a user",
  "user.deactivated": "deactivated a user",
  "user.deleted_permanently": "deleted a user",
  "user.password_reset": "reset a password",
  "user.permissions_set": "changed permissions",
  "user.scopes_set": "changed markets",
  "owner.created": "bootstrapped the owner account",
  "owner.password_reset": "reset the owner password",
  "attribution.backfill": "backfilled pre-RBAC attribution",
  "mapping.create": "mapped an option",
  "mapping.delete": "unmapped an option",
  "competitor.add_url": "added a competitor by URL",
  "competitor.delete_option": "deleted a competitor option",
  "competitor.delete_seller": "deleted a seller",
  "review.approved": "approved a mapping",
  "review.rejected": "rejected a mapping",
};

/** Actions worth colouring. Everything else stays neutral. */
function tone(action: string): { bg: string; border: string; color: string } {
  if (action.startsWith("competitor.delete") || action === "user.deleted_permanently")
    return { bg: "#FEF2F2", border: "#FECACA", color: "#991B1B" };
  if (action === "auth.login_failed" || action === "user.deactivated")
    return { bg: "#FFFAEB", border: "#FEDF89", color: "#92400E" };
  if (action.startsWith("mapping.create") || action.startsWith("user.created"))
    return { bg: "#F0FDF4", border: "#BBF7D0", color: "#166534" };
  return { bg: "#F2F4F7", border: "#E4E7EC", color: "#475467" };
}

function fmtWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return (
    d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" }) +
    " · " +
    d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
  );
}

export function AdminAudit() {
  const toast = useToast();
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [limit, setLimit] = useState(100);
  const [expanded, setExpanded] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await adminApi.audit({ actor, action, limit }));
    } catch (e) {
      toast.error(e instanceof AdminApiError ? e.message : "Could not load the activity log.");
    } finally {
      setLoading(false);
    }
  }, [actor, action, limit, toast]);

  useEffect(() => {
    const t = window.setTimeout(load, 220);
    return () => window.clearTimeout(t);
  }, [load]);

  return (
    <>
      <div className="flex items-end justify-between gap-4 flex-wrap mb-5">
        <div>
          <h1 className="text-[24px] font-bold tracking-[-0.02em] text-[#101828]">
            Activity
          </h1>
          <p className="text-[13px] text-[#667085] mt-1">
            Every write, and who made it. Sign-ins and failed attempts included.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="relative flex-1 min-w-[220px] max-w-[320px]">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-[#98A2B3]" />
          <input
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            placeholder="Filter by person"
            className="w-full pl-9 pr-8 py-2 text-[12.5px] bg-white border border-[#D0D5DD] rounded-[9px] outline-none focus:border-[#EA580C] focus:ring-2 focus:ring-[#FFEDD5] transition"
          />
          {actor && (
            <button
              type="button"
              onClick={() => setActor("")}
              aria-label="Clear"
              className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-[#98A2B3] hover:text-[#101828]"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        <select
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="py-2 pl-3 pr-8 text-[12.5px] bg-white border border-[#D0D5DD] rounded-[9px] outline-none focus:border-[#EA580C] transition cursor-pointer"
        >
          <option value="">All activity</option>
          <option value="auth">Sign-in and passwords</option>
          <option value="user">User administration</option>
          <option value="mapping">Mapping</option>
          <option value="competitor">Competitors</option>
          <option value="review">Review decisions</option>
        </select>
        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="py-2 pl-3 pr-8 text-[12.5px] bg-white border border-[#D0D5DD] rounded-[9px] outline-none focus:border-[#EA580C] transition cursor-pointer tnum"
        >
          {[50, 100, 250, 500].map((n) => (
            <option key={n} value={n}>
              Last {n}
            </option>
          ))}
        </select>
        <span className="ml-auto text-[12px] text-[#667085] tnum">
          {rows.length} entr{rows.length === 1 ? "y" : "ies"}
        </span>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-[13px] text-[#667085] py-20 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading…
        </div>
      ) : rows.length === 0 ? (
        <div className="bg-white border border-dashed border-[#D0D5DD] rounded-[12px] px-8 py-16 text-center text-[13px] text-[#98A2B3]">
          Nothing matches this filter.
        </div>
      ) : (
        <div className="bg-white border border-[#E4E7EC] rounded-[12px] divide-y divide-[#F2F4F7] overflow-hidden">
          {rows.map((r) => {
            const t = tone(r.action);
            const hasDetail = r.before_json != null || r.after_json != null;
            const open = expanded === r.id;
            return (
              <div key={r.id}>
                <button
                  type="button"
                  onClick={() => setExpanded(open ? null : hasDetail ? r.id : null)}
                  disabled={!hasDetail}
                  className={`w-full text-left px-4 py-3 flex items-center gap-3 transition ${
                    hasDetail ? "hover:bg-[#F9FAFB] cursor-pointer" : "cursor-default"
                  }`}
                >
                  <span
                    className="shrink-0 px-2 py-[2px] rounded-full text-[10.5px] font-semibold border"
                    style={{ background: t.bg, borderColor: t.border, color: t.color }}
                  >
                    {ACTION_LABEL[r.action] ?? r.action}
                  </span>
                  <span className="text-[12.5px] text-[#101828] font-medium truncate">
                    {r.actor_email}
                  </span>
                  {r.entity_type && (
                    <span className="text-[11.5px] text-[#98A2B3] truncate">
                      {r.entity_type}
                      {r.entity_id ? ` ${r.entity_id}` : ""}
                    </span>
                  )}
                  <span className="ml-auto shrink-0 flex items-center gap-2.5">
                    {r.ip && (
                      <span className="text-[11px] text-[#98A2B3] font-mono hidden sm:inline">
                        {r.ip}
                      </span>
                    )}
                    <span className="text-[11.5px] text-[#667085] tnum">
                      {fmtWhen(r.created_at)}
                    </span>
                    {hasDetail && (
                      <ChevronDown
                        className={`w-3.5 h-3.5 text-[#98A2B3] transition-transform ${
                          open ? "rotate-180" : ""
                        }`}
                      />
                    )}
                  </span>
                </button>
                {open && (
                  <div className="px-4 pb-3.5 grid gap-3 sm:grid-cols-2">
                    {r.before_json != null && (
                      <Detail label="Before" value={r.before_json} />
                    )}
                    {r.after_json != null && (
                      <Detail label="After" value={r.after_json} />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

function Detail({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[#98A2B3] mb-1">
        {label}
      </div>
      <pre className="text-[11px] font-mono text-[#344054] bg-[#F9FAFB] border border-[#E4E7EC] rounded-[8px] px-3 py-2 overflow-x-auto whitespace-pre-wrap break-words">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
