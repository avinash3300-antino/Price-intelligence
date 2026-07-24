"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
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

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-[248px] shrink-0 bg-[#0C2A29] text-[#CFE3E1] flex flex-col border-r border-[#0A2120]">
      <div className="px-5 pt-[22px] pb-[18px] flex items-center gap-[11px]">
        <div className="w-[34px] h-[34px] rounded-[9px] bg-gradient-to-br from-[#19A89B] to-[#0E6F6A] grid place-items-center text-white font-bold text-base shadow-[0_2px_8px_rgba(13,110,106,0.45)]">
          R
        </div>
        <div className="leading-tight">
          <div className="text-[14px] font-semibold text-white -tracking-[0.01em]">
            Rayna
          </div>
          <div className="text-[11px] font-normal text-[#7FB3AE] tracking-[0.02em]">
            Market Intelligence
          </div>
        </div>
      </div>

      <div className="px-3 pt-2 pb-1 text-[10.5px] font-semibold tracking-[0.09em] uppercase text-[#5E8E89] mt-2">
        Workspace
      </div>
      <nav className="flex flex-col gap-0.5 px-3 py-1">
        {NAV.map((item) => {
          const active = item.matcher(pathname);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-[11px] w-full px-3 py-[9px] rounded-[9px] text-[13.5px] font-medium transition-colors ${
                active
                  ? "bg-[#16403D] text-white"
                  : "text-[#9CC3BE] hover:text-white hover:bg-[#103E3B]/60"
              }`}
            >
              <span className="w-[18px] h-[18px] inline-flex items-center justify-center shrink-0">
                <Icon className="w-[17px] h-[17px]" strokeWidth={2} />
              </span>
              <span className="flex-1">{item.label}</span>
              {item.badge && (
                <span className="tnum bg-[#E0A93C] text-[#3A2606] text-[11px] font-bold min-w-[20px] h-[19px] px-[6px] rounded-[9px] inline-flex items-center justify-center">
                  {item.badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

    </aside>
  );
}
