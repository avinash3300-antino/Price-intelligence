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
  comingSoon?: boolean;
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
    comingSoon: true,
  },
  {
    href: "/review",
    label: "Review",
    icon: CheckSquare,
    matcher: (p) => p === "/review",
    comingSoon: true,
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
      className={`${collapsed ? "w-[68px]" : "w-[248px]"} shrink-0 bg-[#F8F9FB] text-[#344054] flex flex-col border-r border-[#E4E7EC] relative ${hydrated ? "transition-[width] duration-200 ease-out" : ""}`}
    >
      {/* Logo + brand */}
      <div
        className={`${collapsed ? "px-3 justify-center" : "px-5"} pt-[22px] pb-[18px] flex items-center gap-[10px] border-b-2 border-[#E4E7EC]`}
      >
        {collapsed ? (
          /* Collapsed: crop to just the logo mark (flag icon) */
          <img
            src="/rayna-logo.png"
            alt="Rayna Tours"
            className="h-[26px] w-auto object-contain object-left"
          />
        ) : (
          <img
            src="/rayna-logo.png"
            alt="Rayna Tours"
            className="h-[30px] w-auto"
          />
        )}
        {!collapsed && (
          <div className="leading-tight min-w-0 flex-1">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[#475467]">
              Price Intelligence
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
        className="absolute top-[34px] right-[-11px] w-[22px] h-[22px] rounded-full bg-[#F2F4F7] border border-[#E4E7EC] text-[#344054] hover:bg-[#F97316] hover:text-white shadow-[0_2px_6px_rgba(0,0,0,0.35)] flex items-center justify-center transition-colors z-10"
      >
        {collapsed ? (
          <ChevronRight className="w-3 h-3" strokeWidth={2.5} />
        ) : (
          <ChevronLeft className="w-3 h-3" strokeWidth={2.5} />
        )}
      </button>

      {!collapsed && (
        <div className="px-3 pt-2 pb-1 text-[10.5px] font-semibold tracking-[0.09em] uppercase text-[#667085] mt-2">
          Workspace
        </div>
      )}
      <nav
        className={`flex flex-col gap-0.5 py-1 ${collapsed ? "px-2 mt-4" : "px-3"}`}
      >
        {NAV.map((item) => {
          const active = item.matcher(pathname);
          const Icon = item.icon;
          const commonClasses = `flex items-center gap-[11px] w-full py-[9px]  text-[13.5px] font-medium transition-colors ${
            collapsed ? "justify-center px-0" : "px-3"
          }`;

          if (item.comingSoon) {
            const tooltip = collapsed
              ? `${item.label} — Coming soon`
              : "Coming soon";
            return (
              <div
                key={item.href}
                role="link"
                aria-disabled="true"
                title={tooltip}
                className={`${commonClasses} text-[#667085] opacity-70 cursor-not-allowed select-none`}
              >
                <span className="w-[18px] h-[18px] inline-flex items-center justify-center shrink-0">
                  <Icon className="w-[17px] h-[17px]" strokeWidth={2} />
                </span>
                {!collapsed && (
                  <>
                    <span className="flex-1">{item.label}</span>
                    <span className="text-[9.5px] font-semibold uppercase tracking-[0.06em] bg-[#E4E7EC] text-[#667085] border border-[#D0D5DD] px-[7px] py-[2px] ">
                      Soon
                    </span>
                  </>
                )}
              </div>
            );
          }

          return (
            <Link
              key={item.href}
              href={item.href}
              title={collapsed ? item.label : undefined}
              className={`${commonClasses} ${
                active
                  ? "bg-[#F2F4F7] text-[#101828]"
                  : "text-[#475467] hover:text-[#101828] hover:bg-[#F2F4F7]/60"
              }`}
            >
              <span className="w-[18px] h-[18px] inline-flex items-center justify-center shrink-0">
                <Icon className="w-[17px] h-[17px]" strokeWidth={2} />
              </span>
              {!collapsed && (
                <>
                  <span className="flex-1">{item.label}</span>
                  {item.badge && (
                    <span className="tnum bg-[#E0A93C] text-[#3A2606] text-[11px] font-bold min-w-[20px] h-[19px] px-[6px]  inline-flex items-center justify-center">
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
