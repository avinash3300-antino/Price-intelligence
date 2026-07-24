"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  LayoutGrid,
  Workflow,
  ListChecks,
  CheckSquare,
  type LucideIcon,
} from "lucide-react";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  matcher: (path: string) => boolean;
  badge?: number;
}

const NAV: NavItem[] = [
  {
    href: "/",
    label: "Mapping",
    icon: Workflow,
    matcher: (p) => p === "/",
  },
  {
    href: "/mapped",
    label: "Mapped",
    icon: ListChecks,
    matcher: (p) => p === "/mapped",
  },
  {
    href: "/comparison",
    label: "Comparison",
    icon: LayoutGrid,
    matcher: (p) => p === "/comparison" || p.startsWith("/comparison/"),
  },
  {
    href: "/review",
    label: "Review",
    icon: CheckSquare,
    matcher: (p) => p === "/review",
  },
];

const STORAGE_KEY = "rayna-sidebar-collapsed";

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  // Hydrate from localStorage after mount. Doing it in an effect avoids the
  // SSR/CSR mismatch that a `useState(() => localStorage.getItem(...))` would
  // create, since localStorage doesn't exist on the server.
  useEffect(() => {
    try {
      if (localStorage.getItem(STORAGE_KEY) === "1") setCollapsed(true);
    } catch {
      /* localStorage unavailable — stay expanded */
    }
    setHydrated(true);
  }, []);

  function toggle() {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }

  return (
    <aside
      className={`${collapsed ? "w-[68px]" : "w-[248px]"} shrink-0 bg-[#0C2A29] text-[#CFE3E1] flex flex-col border-r border-[#0A2120] relative ${hydrated ? "transition-[width] duration-200 ease-out" : ""}`}
    >
      {/* Logo + brand */}
      <div
        className={`${collapsed ? "px-0 justify-center" : "px-5"} pt-[22px] pb-[18px] flex items-center gap-[11px]`}
      >
        <div className="w-[34px] h-[34px] rounded-[9px] bg-gradient-to-br from-[#19A89B] to-[#0E6F6A] grid place-items-center text-white font-bold text-base shadow-[0_2px_8px_rgba(13,110,106,0.45)] shrink-0">
          R
        </div>
        {!collapsed && (
          <div className="leading-tight min-w-0 flex-1">
            <div className="text-[14px] font-semibold text-white -tracking-[0.01em]">
              Rayna
            </div>
            <div className="text-[11px] font-normal text-[#7FB3AE] tracking-[0.02em]">
              Market Intelligence
            </div>
          </div>
        )}
      </div>

      {/* Collapse toggle — half-outside the right edge */}
      <button
        type="button"
        onClick={toggle}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand" : "Collapse"}
        className="absolute top-[34px] right-[-11px] w-[22px] h-[22px] rounded-full bg-[#16403D] border border-[#0A2120] text-[#CFE3E1] hover:bg-[#0E6F6A] hover:text-white shadow-[0_2px_6px_rgba(0,0,0,0.35)] flex items-center justify-center transition-colors z-10"
      >
        {collapsed ? (
          <ChevronRight className="w-3 h-3" strokeWidth={2.5} />
        ) : (
          <ChevronLeft className="w-3 h-3" strokeWidth={2.5} />
        )}
      </button>

      {!collapsed && (
        <div className="px-3 pt-2 pb-1 text-[10.5px] font-semibold tracking-[0.09em] uppercase text-[#5E8E89] mt-2">
          Workspace
        </div>
      )}
      <nav
        className={`flex flex-col gap-0.5 py-1 ${collapsed ? "px-2 mt-4" : "px-3"}`}
      >
        {NAV.map((item) => {
          const active = item.matcher(pathname);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              title={collapsed ? item.label : undefined}
              className={`flex items-center gap-[11px] w-full py-[9px] rounded-[9px] text-[13.5px] font-medium transition-colors ${
                collapsed ? "justify-center px-0" : "px-3"
              } ${
                active
                  ? "bg-[#16403D] text-white"
                  : "text-[#9CC3BE] hover:text-white hover:bg-[#103E3B]/60"
              }`}
            >
              <span className="w-[18px] h-[18px] inline-flex items-center justify-center shrink-0">
                <Icon className="w-[17px] h-[17px]" strokeWidth={2} />
              </span>
              {!collapsed && (
                <>
                  <span className="flex-1">{item.label}</span>
                  {item.badge && (
                    <span className="tnum bg-[#E0A93C] text-[#3A2606] text-[11px] font-bold min-w-[20px] h-[19px] px-[6px] rounded-[9px] inline-flex items-center justify-center">
                      {item.badge}
                    </span>
                  )}
                </>
              )}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
