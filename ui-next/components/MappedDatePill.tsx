"use client";

import { useMemo, useRef } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { Calendar, ChevronDown } from "lucide-react";

/**
 * Compact date pill for pages that are server-rendered from ``searchParams``.
 * Picking a date navigates the page to ``?date=YYYY-MM-DD`` and the server
 * component re-renders with the new prices. Always displays a real date
 * (defaults to today) so prices always reflect a real bookable day.
 */
export function MappedDatePill({ value }: { value: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const inputRef = useRef<HTMLInputElement>(null);

  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const max = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() + 60);
    return d.toISOString().slice(0, 10);
  }, []);

  function apply(next: string) {
    const q = new URLSearchParams(params?.toString() ?? "");
    q.set("date", next);
    router.push(`${pathname}?${q.toString()}`);
  }

  function openPicker() {
    const el = inputRef.current;
    if (!el) return;
    if (typeof el.showPicker === "function") el.showPicker();
    else el.focus();
  }

  const display = new Date(value + "T00:00:00").toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  const isToday = value === today;

  return (
    <button
      type="button"
      onClick={openPicker}
      className="relative inline-flex items-center gap-2 px-3.5 py-2 rounded-[10px] text-[13px] font-semibold border border-[#F59E0B] bg-[#FFF7ED] text-[#EA580C] hover:bg-white transition-all cursor-pointer"
    >
      <Calendar className="w-3.5 h-3.5" />
      <span>{isToday ? `${display} (today)` : display}</span>
      <ChevronDown className="w-3 h-3 opacity-70" />
      <input
        ref={inputRef}
        type="date"
        min={today}
        max={max}
        value={value}
        onChange={(e) => {
          if (e.target.value) apply(e.target.value);
        }}
        className="absolute inset-0 opacity-0 pointer-events-none"
      />
    </button>
  );
}
