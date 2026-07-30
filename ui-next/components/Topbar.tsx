"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { RefreshCw } from "lucide-react";

interface NavItem {
  href: string;
  label: string;
  matcher: (path: string) => boolean;
  comingSoon?: boolean;
}

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

// Kept in the Props type for source compatibility with existing callers
// (`AppLayout` still forwards title/subtitle) — but no longer rendered.
export interface TopbarProps {
  title?: string;
  subtitle?: string;
}

export function Topbar(_: TopbarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [spinning, setSpinning] = useState(false);

  function handleRefresh() {
    if (spinning) return;
    setSpinning(true);
    router.refresh();
    setTimeout(() => setSpinning(false), 900);
  }

  return (
    <header className="h-[60px] shrink-0 bg-white border-b-2 border-[#E4E7EC] flex items-center px-7 gap-[22px]">
      <Link
        href="/"
        className="shrink-0 flex items-center"
        title="Rayna Tours — Price Intelligence"
      >
        <img
          src="/rayna-logo.svg"
          alt="Rayna Tours"
          className="h-[34px] w-auto"
        />
      </Link>

      <nav className="flex items-center h-full">
        {NAV.map((item) => {
          const active = item.matcher(pathname);
          const base =
            "inline-flex items-center gap-2 px-[14px] h-full text-[13.5px] transition-colors relative";
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
                <span className="text-[9.5px] font-semibold uppercase tracking-[0.06em] bg-[#F2F4F7] text-[#667085] border border-[#E4E7EC] px-[6px] py-[1px]">
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
                  : "font-medium text-[#475467] hover:text-[#101828]"
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

      <div className="ml-auto flex items-center gap-[14px]">
        <div className="flex items-center bg-[#F2F4F7] border border-[#E4E7EC] p-[3px] gap-0.5">
          <button
            type="button"
            className="flex items-center gap-[7px] px-[11px] py-[5px] text-[12.5px] font-semibold bg-white text-[#EA580C] shadow-sm transition-colors"
          >
            <span className="text-[13px]">🇦🇪</span>
            UAE · AED
          </button>
          <button
            type="button"
            disabled
            className="flex items-center gap-[7px] px-[11px] py-[5px] text-[12.5px] font-medium bg-transparent text-[#98A2B3] cursor-not-allowed"
          >
            <span className="text-[13px] grayscale opacity-70">🇮🇳</span>
            India · INR
            <span className="text-[9.5px] font-semibold bg-[#F2F4F7] text-[#667085] px-[6px] py-px tracking-[0.03em]">
              SOON
            </span>
          </button>
        </div>

        <button
          type="button"
          onClick={handleRefresh}
          title="Refresh"
          className="w-[34px] h-[34px] border border-[#E4E7EC] bg-white flex items-center justify-center text-[#475467] hover:bg-[#F2F4F7] transition-colors"
        >
          <RefreshCw
            className={`w-4 h-4 ${spinning ? "animate-spin" : ""}`}
            strokeWidth={2}
          />
        </button>

        <div className="w-[32px] h-[32px] rounded-full bg-gradient-to-br from-[#F97316] to-[#EA580C] text-white flex items-center justify-center text-[12.5px] font-semibold">
          AK
        </div>
      </div>
    </header>
  );
}
