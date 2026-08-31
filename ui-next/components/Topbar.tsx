"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { API_BASE_PUBLIC, type SessionUser } from "@/lib/api";
import { UserMenu } from "@/components/UserMenu";

interface NavItem {
  href: string;
  label: string;
  matcher: (path: string) => boolean;
  comingSoon?: boolean;
  // Tab is only rendered when the signed-in user holds this permission.
  // Hiding rather than disabling: a tab you can never open is just noise.
  permission?: string;
  adminOnly?: boolean;
}

// Only the tabs the project actually has — the header styling is copied
// from the v2 mockup (bold active label + orange underline stripe), but
// no extra Overview/Jobs/Competitors placeholders.
const NAV: NavItem[] = [
  {
    href: "/",
    label: "Mapping",
    matcher: (p) => p === "/",
    permission: "mapping.view",
  },
  {
    href: "/mapped",
    label: "Mapped",
    matcher: (p) => p === "/mapped",
    permission: "mapped.view",
  },
  {
    href: "/comparison",
    label: "Comparison",
    matcher: (p) => p === "/comparison" || p.startsWith("/comparison/"),
    permission: "comparison.view",
  },
  {
    href: "/review",
    label: "Review",
    matcher: (p) => p === "/review",
    permission: "review.decide",
  },
  {
    href: "/admin",
    label: "Admin",
    matcher: (p) => p.startsWith("/admin"),
    adminOnly: true,
  },
];

export interface TopbarProps {
  title?: string;
  subtitle?: string;
  user: SessionUser;
}

export function Topbar({ user }: TopbarProps) {
  const pathname = usePathname();
  const visibleNav = NAV.filter((item) => {
    if (item.adminOnly) return user.role === "admin";
    if (item.permission) return user.permissions.includes(item.permission);
    return true;
  });
  const [crawledLabel, setCrawledLabel] = useState<string | null>(null);

  // Cheap "live" heartbeat for the status pill: if /api/health responds OK,
  // show "crawler live". A real "last crawled" timestamp can be plumbed in
  // later once the backend exposes one.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${API_BASE_PUBLIC}/api/health`, {
          cache: "no-store",
          credentials: "include",
        });
        if (r.ok && !cancelled) {
          const body = (await r.json()) as { ok?: boolean };
          setCrawledLabel(body?.ok ? "crawler live" : null);
        }
      } catch {
        /* silent */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <header className="h-[60px] shrink-0 bg-white border-b border-[#E4E7EC] flex items-center px-6 gap-5">
      <Link
        href="/"
        className="shrink-0 flex flex-col items-start leading-none"
        title="Rayna Tours — Price Intelligence"
      >
        <img
          src="/rayna-logo.png"
          alt="Rayna Tours"
          className="h-[30px] w-auto"
        />
        <span className="mt-[3px] text-[6px] font-semibold uppercase tracking-[0.14em] text-[#101828]">
          Price Intelligence
        </span>
      </Link>

      <nav className="flex items-center h-full">
        {visibleNav.map((item) => {
          const active = item.matcher(pathname);
          const base =
            "inline-flex items-center gap-2 px-[13px] h-full text-[13.5px] transition-colors relative";
          if (item.comingSoon) {
            return (
              <div
                key={item.href}
                title="Coming soon"
                role="link"
                aria-disabled="true"
                className={`${base} font-medium text-[#98A2B3] cursor-not-allowed select-none`}
              >
                {item.label}
                <span className="text-[9.5px] font-semibold uppercase tracking-[0.06em] bg-[#F2F4F7] text-[#667085] border border-[#E4E7EC] px-[6px] py-[1px] rounded-[999px]">
                  Soon
                </span>
              </div>
            );
          }
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`${base} ${
                active
                  ? "font-semibold text-[#101828]"
                  : "font-medium text-[#667085] hover:text-[#101828]"
              }`}
            >
              {item.label}
              {active && (
                <span
                  aria-hidden
                  className="absolute left-0 right-0 bottom-0 h-[2px] bg-[#EA580C]"
                />
              )}
            </Link>
          );
        })}
      </nav>

      <div className="ml-auto flex items-center gap-4">
        {crawledLabel && (
          <span className="tnum inline-flex items-center gap-[7px] text-[12px] text-[#667085]">
            <span className="w-2 h-2 rounded-full bg-[#12B76A]" />
            {crawledLabel}
          </span>
        )}
        <UserMenu user={user} />
      </div>
    </header>
  );
}
