"use client";

import { useEffect, useRef, useState } from "react";
import { KeyRound, LogOut, MapPin, ShieldCheck } from "lucide-react";
import type { SessionUser } from "@/lib/api";

function initials(name: string, email: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  if (parts.length === 1 && parts[0].length >= 2) return parts[0].slice(0, 2).toUpperCase();
  return email.slice(0, 2).toUpperCase();
}

/** "UAE · Dubai, Abu Dhabi" — or the whole country when city is null. */
function scopeSummary(user: SessionUser): string {
  if (user.role === "admin") return "All countries and cities";
  if (user.scopes.length === 0) return "No markets assigned";
  const byCountry = new Map<string, string[]>();
  for (const s of user.scopes) {
    const cities = byCountry.get(s.country) ?? [];
    if (s.city) cities.push(s.city);
    byCountry.set(s.country, cities);
  }
  return Array.from(byCountry.entries())
    .map(([country, cities]) =>
      cities.length ? `${country} · ${cities.join(", ")}` : `${country} (all cities)`,
    )
    .join(" • ");
}

export function UserMenu({ user }: { user: SessionUser }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function signOut() {
    setBusy(true);
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    // Full navigation so every server component re-renders without the cookie.
    window.location.href = "/login";
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={user.email}
        className="w-[30px] h-[30px] rounded-full bg-gradient-to-br from-[#F59E0B] to-[#EA580C] text-white flex items-center justify-center text-[12px] font-bold outline-none focus-visible:ring-2 focus-visible:ring-[#FDBA74] hover:brightness-105 transition"
      >
        {initials(user.full_name, user.email)}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-[38px] z-50 w-[286px] bg-white border border-[#E4E7EC] rounded-[12px] shadow-[0_12px_32px_rgba(16,24,40,0.14)] overflow-hidden"
        >
          <div className="px-4 py-3.5 border-b border-[#F2F4F7]">
            <div className="text-[13.5px] font-semibold text-[#101828] truncate">
              {user.full_name}
            </div>
            <div className="text-[11.5px] text-[#667085] truncate">{user.email}</div>
            <div className="mt-2 flex items-center gap-1.5 flex-wrap">
              <span
                className="inline-flex items-center gap-1 px-2 py-[2px] rounded-full text-[10.5px] font-semibold border"
                style={
                  user.role === "admin"
                    ? { color: "#92400E", background: "#FFFAEB", borderColor: "#FEDF89" }
                    : { color: "#475467", background: "#F2F4F7", borderColor: "#E4E7EC" }
                }
              >
                <ShieldCheck className="w-3 h-3" />
                {user.role === "admin" ? "Administrator" : "User"}
              </span>
              {user.is_owner && (
                <span className="inline-flex items-center px-2 py-[2px] rounded-full text-[10.5px] font-semibold border border-[#FED7AA] bg-[#FFF4ED] text-[#C2410C]">
                  Owner
                </span>
              )}
            </div>
          </div>

          <div className="px-4 py-3 border-b border-[#F2F4F7]">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[#98A2B3] mb-1.5">
              Markets
            </div>
            <div className="flex items-start gap-1.5">
              <MapPin className="w-3.5 h-3.5 text-[#98A2B3] mt-[1px] shrink-0" />
              <span className="text-[12px] text-[#344054] leading-snug">
                {scopeSummary(user)}
              </span>
            </div>
            <div className="text-[11px] text-[#98A2B3] mt-2 tnum">
              {user.permissions.length} permission
              {user.permissions.length === 1 ? "" : "s"}
            </div>
          </div>

          <a
            href="/change-password"
            role="menuitem"
            className="flex items-center gap-2.5 px-4 py-2.5 text-[12.5px] text-[#344054] hover:bg-[#F9FAFB] transition"
          >
            <KeyRound className="w-3.5 h-3.5 text-[#667085]" />
            Change password
          </a>
          <button
            type="button"
            role="menuitem"
            onClick={signOut}
            disabled={busy}
            className="w-full flex items-center gap-2.5 px-4 py-2.5 text-[12.5px] text-[#B42318] hover:bg-[#FEF2F2] transition disabled:opacity-60 border-t border-[#F2F4F7]"
          >
            <LogOut className="w-3.5 h-3.5" />
            {busy ? "Signing out…" : "Sign out"}
          </button>
        </div>
      )}
    </div>
  );
}
