"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { API_BASE_PUBLIC } from "@/lib/api";

interface NavItem {
  href: string;
  label: string;
  matcher: (path: string) => boolean;
  comingSoon?: boolean;
}

// Only the tabs the project actually has — the header styling is copied
// from the v2 mockup (bold active label + orange underline stripe), but
// no extra Overview/Jobs/Competitors placeholders.
const NAV: NavItem[] = [
  { href: "/", label: "Mapping", matcher: (p) => p === "/" },
  { href: "/mapped", label: "Mapped", matcher: (p) => p === "/mapped" },
  {
    href: "/comparison",
    label: "Comparison",
    matcher: (p) => p === "/comparison" || p.startsWith("/comparison/"),
    comingSoon: true,
  },
  {
    href: "/review",
    label: "Review",
    matcher: (p) => p === "/review",
    comingSoon: true,
  },
];

export interface TopbarProps {
  title?: string;
  subtitle?: string;
}

export function Topbar(_: TopbarProps) {
  const pathname = usePathname();
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
        className="shrink-0 flex items-center"
        title="Rayna Tours — Price Intelligence"
      >
        <img
          src="/rayna-logo.svg"
          alt="Rayna Tours"
          className="h-[30px] w-auto"
        />
      </Link>

      <nav className="flex items-center h-full">
        {NAV.map((item) => {
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
        <div className="w-[30px] h-[30px] rounded-full bg-gradient-to-br from-[#F59E0B] to-[#EA580C] text-white flex items-center justify-center text-[12px] font-bold">
          AK
        </div>
      </div>
    </header>
  );
}
