"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search, X } from "lucide-react";

export interface SearchableSelectProps {
  value: string; // "all" or one of the option values
  onChange: (v: string) => void;
  options: string[];
  allLabel: string; // e.g. "All countries"
  placeholder?: string; // shown inside the search box
  disabled?: boolean;
  className?: string;
  optionMono?: boolean; // render options in a monospace font (for seller domains)
}

/**
 * Lightweight searchable single-select. Replaces native <select> when the
 * option list is long enough that scanning by eye is slow. Behavior:
 *   - Click the trigger button to open the popover.
 *   - Type to filter (case-insensitive substring match).
 *   - Arrow-up/down + Enter to keyboard-navigate; Escape to close.
 *   - Click outside or press the trigger again to close.
 *
 * State-only, no forms library, no portal — the popover is absolutely
 * positioned right below the trigger.
 */
export function SearchableSelect({
  value,
  onChange,
  options,
  allLabel,
  placeholder = "Search…",
  disabled,
  className = "",
  optionMono = false,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [highlight, setHighlight] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Filtered list, always prepended with the "All …" sentinel row.
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((o) => o.toLowerCase().includes(needle));
  }, [options, q]);

  // rows[0] is always the "All" row; option rows follow.
  const rows: { key: string; label: string; isAll: boolean }[] = useMemo(
    () => [
      { key: "all", label: `${allLabel} (${options.length})`, isAll: true },
      ...filtered.map((o) => ({ key: o, label: o, isAll: false })),
    ],
    [allLabel, filtered, options.length],
  );

  // Clamp highlight when the list length changes.
  useEffect(() => {
    if (highlight >= rows.length) setHighlight(0);
  }, [rows.length, highlight]);

  // Close on click-outside.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onDoc);
    return () => window.removeEventListener("mousedown", onDoc);
  }, [open]);

  // Focus the search box + reset transient state on open.
  useEffect(() => {
    if (open) {
      setQ("");
      setHighlight(0);
      const t = setTimeout(() => searchRef.current?.focus(), 10);
      return () => clearTimeout(t);
    }
  }, [open]);

  function commit(key: string) {
    onChange(key);
    setOpen(false);
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, rows.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const row = rows[highlight];
      if (row) commit(row.key);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  }

  const triggerLabel =
    value === "all"
      ? `${allLabel} (${options.length})`
      : value;

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => !disabled && setOpen((o) => !o)}
        disabled={disabled}
        className={`w-full inline-flex items-center gap-2 px-3 py-2 text-[12.5px] bg-white border rounded-[9px] transition ${
          open
            ? "border-[#EA580C] ring-2 ring-[#FFEDD5]"
            : "border-[#D0D5DD] hover:border-[#98A2B3]"
        } ${disabled ? "opacity-50 cursor-not-allowed" : ""} ${
          optionMono && value !== "all" ? "font-mono" : ""
        }`}
      >
        <span className="truncate flex-1 text-left">{triggerLabel}</span>
        <ChevronDown
          className={`w-3.5 h-3.5 text-[#667085] shrink-0 transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div className="absolute z-30 top-[calc(100%+4px)] left-0 min-w-full max-w-[360px] w-max bg-white border border-[#E4E7EC] rounded-[10px] shadow-[0_12px_28px_rgba(16,24,40,0.12)] overflow-hidden">
          <div className="relative border-b border-[#F2F4F7]">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-[#98A2B3]" />
            <input
              ref={searchRef}
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={onKey}
              placeholder={placeholder}
              className="w-full pl-9 pr-8 py-2 text-[12.5px] outline-none"
            />
            {q && (
              <button
                type="button"
                onClick={() => {
                  setQ("");
                  searchRef.current?.focus();
                }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[#98A2B3] hover:text-[#101828] p-0.5"
                aria-label="Clear"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <div className="max-h-[280px] overflow-y-auto py-1">
            {rows.length === 1 ? (
              <div className="px-3 py-2.5 text-[12px] text-[#98A2B3]">
                No matches.
              </div>
            ) : (
              rows.map((row, i) => {
                const active = value === row.key;
                const isHi = i === highlight;
                return (
                  <button
                    key={row.key}
                    type="button"
                    onMouseEnter={() => setHighlight(i)}
                    onClick={() => commit(row.key)}
                    className={`w-full flex items-center gap-2 px-3 py-2 text-[12.5px] text-left transition-colors ${
                      isHi ? "bg-[#F9FAFB]" : ""
                    } ${
                      active
                        ? "text-[#EA580C] font-semibold"
                        : "text-[#101828]"
                    } ${row.isAll ? "" : optionMono ? "font-mono" : ""}`}
                  >
                    <span className="truncate flex-1">{row.label}</span>
                    {active && (
                      <Check className="w-3.5 h-3.5 shrink-0 text-[#EA580C]" />
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
