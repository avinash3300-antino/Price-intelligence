"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, ChevronRight, ExternalLink, Search, X } from "lucide-react";
import { UnmapButton } from "@/components/UnmapButton";
import { SearchableSelect } from "@/components/SearchableSelect";
import { fmtMoney, fmtBasis, fmtAED, toAED } from "@/lib/format";
import type { MappedItem } from "@/lib/api";

type GapKind = "leader" | "over" | "match" | "unknown" | "basis_mismatch";

interface GapDisplay {
  kind: GapKind;
  label: string;
  className: string;
}

function computeGap(m: MappedItem): GapDisplay {
  if (m.rayna_basis !== m.competitor_basis) {
    return {
      kind: "basis_mismatch",
      label: "basis ⚠",
      className: "text-[#B54708]",
    };
  }
  const r = toAED(m.rayna_price, m.rayna_currency);
  const c = toAED(m.competitor_price, m.competitor_currency);
  if (r == null || c == null) {
    return { kind: "unknown", label: "—", className: "text-[#98A2B3]" };
  }
  const diff = c - r;
  const pct = (diff / r) * 100;
  if (Math.abs(diff) < 0.5) {
    return { kind: "match", label: "= 0.0%", className: "text-[#475467]" };
  }
  if (diff > 0) {
    return {
      kind: "leader",
      label: `▼ −${pct.toFixed(1)}%`,
      className: "text-[#067647] font-semibold",
    };
  }
  return {
    kind: "over",
    label: `▲ +${Math.abs(pct).toFixed(1)}%`,
    className: "text-[#B42318] font-semibold",
  };
}

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso);
    return (
      d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" }) +
      " · " +
      d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
    );
  } catch {
    return iso;
  }
}

type PositionFilter = "all" | GapKind;

type SortKey =
  | "rayna_option"
  | "seller"
  | "competitor_option"
  | "rayna_price"
  | "competitor_price"
  | "gap"
  | "mapped";
type SortDir = "asc" | "desc";

export function MappedFilters({ items }: { items: MappedItem[] }) {
  const [q, setQ] = useState("");
  const [seller, setSeller] = useState<string>("all");
  const [position, setPosition] = useState<PositionFilter>("all");
  const [country, setCountry] = useState<string>("all");
  const [city, setCity] = useState<string>("all");
  // Default: newest mapping first — matches the backend's ORDER BY created_at DESC
  const [sortKey, setSortKey] = useState<SortKey>("mapped");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  // Grouped view: one Rayna option can be mapped to multiple competitor
  // options (one per seller). Group by rayna_option_id and let the user
  // expand a group to see its mappings. Closed by default per user preference.
  const [openGroups, setOpenGroups] = useState<Set<number>>(new Set());
  function toggleGroup(key: number) {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  // Precompute gaps once
  const gaps = useMemo(() => items.map(computeGap), [items]);

  const sellers = useMemo(() => {
    const s = new Set<string>();
    items.forEach((m) => s.add(m.seller_domain));
    return Array.from(s).sort();
  }, [items]);

  const countries = useMemo(() => {
    const s = new Set<string>();
    items.forEach((m) => {
      if (m.product_country) s.add(m.product_country);
    });
    return Array.from(s).sort();
  }, [items]);

  // Cities cascade off the selected country — if "All countries" is picked,
  // show every distinct city; otherwise scope to that country.
  const cities = useMemo(() => {
    const s = new Set<string>();
    items.forEach((m) => {
      if (!m.product_city) return;
      if (country !== "all" && m.product_country !== country) return;
      s.add(m.product_city);
    });
    return Array.from(s).sort();
  }, [items, country]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const rows = items
      .map((m, i) => ({ m, gap: gaps[i] }))
      .filter(({ m, gap }) => {
        if (country !== "all" && m.product_country !== country) return false;
        if (city !== "all" && m.product_city !== city) return false;
        if (seller !== "all" && m.seller_domain !== seller) return false;
        if (position !== "all" && gap.kind !== position) return false;
        if (needle) {
          const hay = `${m.rayna_option_name} ${m.competitor_option_name} ${m.product_name} ${m.seller_domain}`.toLowerCase();
          if (!hay.includes(needle)) return false;
        }
        return true;
      });

    // Sort helpers. For "gap" we sort on the numeric percentage (competitor -
    // rayna) / rayna so users can find biggest wins / worst overpricing fast.
    // basis_mismatch and unknown rows get pushed to the end regardless of dir
    // so the sort remains meaningful.
    const gapValue = (row: { m: MappedItem; gap: GapDisplay }): number | null => {
      if (row.gap.kind === "basis_mismatch" || row.gap.kind === "unknown") return null;
      const r = toAED(row.m.rayna_price, row.m.rayna_currency);
      const c = toAED(row.m.competitor_price, row.m.competitor_currency);
      if (r == null || c == null || r === 0) return null;
      return (c - r) / r;
    };
    const priceInAed = (p: number | null, cur: string | null): number | null =>
      toAED(p, cur);
    const cmpStr = (a: string, b: string) =>
      a.localeCompare(b, undefined, { sensitivity: "base" });

    rows.sort((A, B) => {
      const dir = sortDir === "asc" ? 1 : -1;
      switch (sortKey) {
        case "rayna_option":
          return cmpStr(A.m.rayna_option_name, B.m.rayna_option_name) * dir;
        case "seller":
          return cmpStr(A.m.seller_domain, B.m.seller_domain) * dir;
        case "competitor_option":
          return (
            cmpStr(A.m.competitor_option_name, B.m.competitor_option_name) * dir
          );
        case "rayna_price": {
          const a = priceInAed(A.m.rayna_price, A.m.rayna_currency);
          const b = priceInAed(B.m.rayna_price, B.m.rayna_currency);
          if (a == null && b == null) return 0;
          if (a == null) return 1;
          if (b == null) return -1;
          return (a - b) * dir;
        }
        case "competitor_price": {
          const a = priceInAed(A.m.competitor_price, A.m.competitor_currency);
          const b = priceInAed(B.m.competitor_price, B.m.competitor_currency);
          if (a == null && b == null) return 0;
          if (a == null) return 1;
          if (b == null) return -1;
          return (a - b) * dir;
        }
        case "gap": {
          const a = gapValue(A);
          const b = gapValue(B);
          if (a == null && b == null) return 0;
          if (a == null) return 1;
          if (b == null) return -1;
          return (a - b) * dir;
        }
        case "mapped":
        default:
          return A.m.created_at.localeCompare(B.m.created_at) * dir;
      }
    });

    return rows;
  }, [items, gaps, q, seller, position, country, city, sortKey, sortDir]);

  // Group the sorted+filtered flat list by rayna_option_id, preserving the
  // order in which each group's first row appeared (so the outer sort still
  // determines group order).
  const grouped = useMemo(() => {
    const groups = new Map<
      number,
      { key: number; header: MappedItem; rows: Array<{ m: MappedItem; gap: GapDisplay }> }
    >();
    for (const row of filtered) {
      const key = row.m.rayna_option_id;
      if (!groups.has(key)) {
        groups.set(key, { key, header: row.m, rows: [] });
      }
      groups.get(key)!.rows.push(row);
    }
    return Array.from(groups.values());
  }, [filtered]);

  function expandAll() {
    setOpenGroups(new Set(grouped.map((g) => g.key)));
  }
  function collapseAll() {
    setOpenGroups(new Set());
  }
  const allOpen = grouped.length > 0 && openGroups.size === grouped.length;

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      // Numeric / date columns feel more natural starting descending
      // (biggest gap first, newest mapping first). Text columns start asc.
      const numericOrDate: SortKey[] = [
        "rayna_price",
        "competitor_price",
        "gap",
        "mapped",
      ];
      setSortDir(numericOrDate.includes(key) ? "desc" : "asc");
    }
  }

  const nLeader = gaps.filter((g) => g.kind === "leader").length;
  const nOver = gaps.filter((g) => g.kind === "over").length;
  const nParity = gaps.filter((g) => g.kind === "match").length;
  const nBasis = gaps.filter((g) => g.kind === "basis_mismatch").length;

  const activeFilter =
    !!q ||
    seller !== "all" ||
    position !== "all" ||
    country !== "all" ||
    city !== "all";

  return (
    <>
      {/* Stat strip — clickable to filter */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        <StatCard
          label="Mappings"
          value={items.length}
          tone="neutral"
          active={position === "all"}
          onClick={() => setPosition("all")}
        />
        <StatCard
          label="Price leader"
          value={nLeader}
          sub={nLeader === 1 ? "product" : "products"}
          tone="good"
          active={position === "leader"}
          onClick={() =>
            setPosition(position === "leader" ? "all" : "leader")
          }
        />
        <StatCard
          label="Over market"
          value={nOver}
          sub={nOver === 1 ? "product" : "products"}
          tone="bad"
          active={position === "over"}
          onClick={() => setPosition(position === "over" ? "all" : "over")}
        />
        <StatCard
          label={nBasis > 0 ? "Basis mismatch" : "At parity"}
          value={nBasis > 0 ? nBasis : nParity}
          sub={nBasis > 0 ? "needs review" : "at market"}
          tone={nBasis > 0 ? "warn" : "neutral"}
          active={
            nBasis > 0 ? position === "basis_mismatch" : position === "match"
          }
          onClick={() => {
            const target: PositionFilter = nBasis > 0 ? "basis_mismatch" : "match";
            setPosition(position === target ? "all" : target);
          }}
        />
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="relative flex-1 min-w-[240px] max-w-[420px]">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-[#98A2B3]" />
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search Rayna option, competitor option, or product"
            className="w-full pl-9 pr-8 py-2 text-[12.5px] bg-white border border-[#D0D5DD] rounded-[9px] outline-none focus:border-[#EA580C] focus:ring-2 focus:ring-[#FFEDD5] transition"
          />
          {q && (
            <button
              type="button"
              onClick={() => setQ("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[#98A2B3] hover:text-[#101828] p-0.5"
              aria-label="Clear search"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        <SearchableSelect
          value={country}
          onChange={(v) => {
            setCountry(v);
            // Changing country resets city so we don't end up with a
            // country/city combo that no mapping actually has.
            setCity("all");
          }}
          options={countries}
          allLabel="All countries"
          placeholder="Search country"
          className="min-w-[180px]"
        />

        <SearchableSelect
          value={city}
          onChange={setCity}
          options={cities}
          allLabel="All cities"
          placeholder="Search city"
          disabled={cities.length === 0}
          className="min-w-[160px]"
        />

        <SearchableSelect
          value={seller}
          onChange={setSeller}
          options={sellers}
          allLabel="All sellers"
          placeholder="Search seller"
          optionMono
          className="min-w-[180px]"
        />

        {activeFilter && (
          <button
            type="button"
            onClick={() => {
              setQ("");
              setSeller("all");
              setPosition("all");
              setCountry("all");
              setCity("all");
            }}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-[12px] font-semibold text-[#475467] hover:text-[#101828] hover:bg-[#F2F4F7] rounded-[7px] transition"
          >
            <X className="w-3.5 h-3.5" />
            Clear
          </button>
        )}

        <span className="ml-auto text-[12px] text-[#667085] tnum">
          Showing{" "}
          <span className="font-semibold text-[#101828]">
            {grouped.length}
          </span>{" "}
          option{grouped.length === 1 ? "" : "s"} ·{" "}
          <span className="font-semibold text-[#101828]">{filtered.length}</span>{" "}
          mapping{filtered.length === 1 ? "" : "s"}
        </span>
      </div>

      {/* Grouped table — one card per Rayna option, expandable to reveal
          the seller mappings underneath. */}
      <div className="bg-white border border-[#E4E7EC] rounded-[12px] overflow-hidden">
        {/* Column headers — match the sub-row grid so alignments feel intentional. */}
        <div className="hidden md:grid grid-cols-[24px_2.4fr_1.2fr_2.2fr_1fr_0.9fr_0.9fr_70px] gap-3 px-4 py-3 bg-[#F9FAFB] border-b border-[#E4E7EC] text-[10.5px] font-semibold tracking-[0.05em] uppercase text-[#667085]">
          <button
            type="button"
            onClick={allOpen ? collapseAll : expandAll}
            className="text-[#667085] hover:text-[#101828] transition-colors"
            title={allOpen ? "Collapse all" : "Expand all"}
          >
            {allOpen ? (
              <ChevronDown className="w-3.5 h-3.5" strokeWidth={2.5} />
            ) : (
              <ChevronRight className="w-3.5 h-3.5" strokeWidth={2.5} />
            )}
          </button>
          <SortHeader
            label="Rayna option"
            active={sortKey === "rayna_option"}
            dir={sortDir}
            onClick={() => toggleSort("rayna_option")}
          />
          <SortHeader
            label="Seller"
            active={sortKey === "seller"}
            dir={sortDir}
            onClick={() => toggleSort("seller")}
          />
          <SortHeader
            label="Competitor option"
            active={sortKey === "competitor_option"}
            dir={sortDir}
            onClick={() => toggleSort("competitor_option")}
          />
          <SortHeader
            label="Competitor"
            align="right"
            active={sortKey === "competitor_price"}
            dir={sortDir}
            onClick={() => toggleSort("competitor_price")}
          />
          <SortHeader
            label="Gap"
            align="right"
            active={sortKey === "gap"}
            dir={sortDir}
            onClick={() => toggleSort("gap")}
          />
          <SortHeader
            label="Mapped"
            active={sortKey === "mapped"}
            dir={sortDir}
            onClick={() => toggleSort("mapped")}
          />
          <span />
        </div>
        {grouped.length === 0 ? (
          <div className="px-5 py-16 text-center text-[13px] text-[#98A2B3]">
            No mappings match this filter.
          </div>
        ) : (
          <div className="divide-y divide-[#F2F4F7]">
            {grouped.map((g) => (
              <GroupBlock
                key={g.key}
                group={g}
                open={openGroups.has(g.key)}
                onToggle={() => toggleGroup(g.key)}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function GroupBlock({
  group,
  open,
  onToggle,
}: {
  group: {
    key: number;
    header: MappedItem;
    rows: Array<{ m: MappedItem; gap: GapDisplay }>;
  };
  open: boolean;
  onToggle: () => void;
}) {
  const { header, rows } = group;
  const n = rows.length;

  // Aggregate gap range for the closed summary — best (most competitive for
  // Rayna) to worst. Skip basis_mismatch/unknown rows.
  const gapPcts = rows
    .map((r) => {
      if (r.gap.kind === "basis_mismatch" || r.gap.kind === "unknown") return null;
      const rAed = toAED(r.m.rayna_price, r.m.rayna_currency);
      const cAed = toAED(r.m.competitor_price, r.m.competitor_currency);
      if (rAed == null || cAed == null || rAed === 0) return null;
      return ((cAed - rAed) / rAed) * 100;
    })
    .filter((v): v is number => v != null);
  const gapMin = gapPcts.length ? Math.min(...gapPcts) : null;
  const gapMax = gapPcts.length ? Math.max(...gapPcts) : null;
  const gapSummary =
    gapMin == null || gapMax == null
      ? null
      : Math.abs(gapMax - gapMin) < 0.5
        ? fmtSignedPct(gapMin)
        : `${fmtSignedPct(gapMin)} to ${fmtSignedPct(gapMax)}`;
  const gapTone =
    gapMax == null
      ? "text-[#98A2B3]"
      : gapMax < -0.5
        ? "text-[#067647]"
        : gapMin != null && gapMin > 0.5
          ? "text-[#B42318]"
          : "text-[#475467]";

  return (
    <div>
      {/* Group header — clickable to expand/collapse. */}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full grid grid-cols-[24px_2.4fr_1.2fr_2.2fr_1fr_0.9fr_0.9fr_70px] gap-3 px-4 py-3.5 text-left hover:bg-[#F9FAFB] transition-colors items-center"
      >
        <span className="text-[#667085]">
          {open ? (
            <ChevronDown className="w-4 h-4" strokeWidth={2.5} />
          ) : (
            <ChevronRight className="w-4 h-4" strokeWidth={2.5} />
          )}
        </span>
        {/* Rayna option + product name + basis */}
        <div className="min-w-0">
          <div className="text-[13.5px] font-semibold text-[#101828] leading-snug line-clamp-2">
            {header.rayna_option_name}
          </div>
          <div className="text-[11px] text-[#98A2B3] mt-1 flex items-center gap-1.5">
            <span className="truncate">{header.product_name}</span>
            <span className="text-[#D0D5DD]">·</span>
            <span className="font-mono">{fmtBasis(header.rayna_basis)}</span>
            <span className="text-[#D0D5DD]">·</span>
            <span className="tnum font-semibold text-[#344054]">
              {fmtAED(header.rayna_price, header.rayna_currency)}
            </span>
          </div>
        </div>
        {/* Seller count pill */}
        <div className="text-[11.5px] text-[#667085]">
          <span className="inline-flex items-center gap-1.5 px-2 py-[3px] rounded-full bg-[#FFF4ED] border border-[#FED7AA] text-[#C2410C] font-semibold tnum">
            {n} seller{n === 1 ? "" : "s"}
          </span>
        </div>
        {/* Aggregate: sellers listed inline when closed */}
        <div className="text-[11.5px] text-[#667085] truncate">
          {rows
            .map((r) => r.m.seller_domain)
            .filter((v, i, a) => a.indexOf(v) === i)
            .join(", ")}
        </div>
        {/* Competitor price range (closed summary) */}
        <div className="text-right text-[11.5px] text-[#98A2B3]">
          {(() => {
            const prices = rows
              .map((r) => toAED(r.m.competitor_price, r.m.competitor_currency))
              .filter((v): v is number => v != null);
            if (prices.length === 0) return "—";
            const lo = Math.min(...prices);
            const hi = Math.max(...prices);
            return lo === hi
              ? fmtAED(lo, "AED")
              : `${fmtAED(lo, "AED")} – ${fmtAED(hi, "AED")}`;
          })()}
        </div>
        {/* Gap range */}
        <div className={`text-right tnum text-[12px] font-semibold ${gapTone}`}>
          {gapSummary ?? "—"}
        </div>
        {/* Newest mapping date */}
        <div className="text-[11px] text-[#98A2B3] tnum whitespace-nowrap">
          {fmtDate(
            rows
              .map((r) => r.m.created_at)
              .sort()
              .reverse()[0]!,
          )}
        </div>
        <span />
      </button>

      {/* Expanded sub-rows — one per mapping (seller). */}
      {open && (
        <div className="bg-[#FBFBFC] border-t border-[#F2F4F7] divide-y divide-[#F2F4F7]">
          {rows.map(({ m, gap }) => (
            <div
              key={m.mapping_id}
              className="grid grid-cols-[24px_2.4fr_1.2fr_2.2fr_1fr_0.9fr_0.9fr_70px] gap-3 px-4 py-3 items-center hover:bg-white transition-colors"
            >
              <span />
              {/* Indent under the group header — subtle */}
              <span className="text-[11.5px] text-[#98A2B3] pl-1">
                ↳ mapping
              </span>
              <a
                href={m.listing_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[12.5px] font-mono text-[#344054] hover:text-[#EA580C] inline-flex items-center gap-1.5 truncate"
              >
                {m.seller_domain}
                <ExternalLink className="w-3 h-3 opacity-50 shrink-0" />
              </a>
              <div className="min-w-0">
                <div className="text-[13px] text-[#101828] line-clamp-2 leading-snug">
                  {m.competitor_option_name}
                </div>
                <div className="text-[11px] text-[#98A2B3] font-mono mt-1">
                  {fmtBasis(m.competitor_basis)}
                </div>
              </div>
              <div className="text-right whitespace-nowrap">
                <div className="tnum text-[13px] font-semibold text-[#101828]">
                  {fmtAED(m.competitor_price, m.competitor_currency)}
                </div>
                {m.competitor_price != null &&
                  (m.competitor_currency || "AED").toUpperCase() !== "AED" && (
                    <div className="tnum text-[10.5px] text-[#98A2B3]">
                      {fmtMoney(m.competitor_price, m.competitor_currency)}
                    </div>
                  )}
                {m.competitor_date_price_source === "default" && (
                  <div
                    title="No observation for this date; showing default variant price"
                    className="inline-flex items-center gap-1 text-[9.5px] text-[#B54708] font-semibold mt-0.5"
                  >
                    <AlertTriangle className="w-3 h-3" />
                    default
                  </div>
                )}
              </div>
              <div className={`text-right whitespace-nowrap tnum text-[12.5px] ${gap.className}`}>
                {gap.label}
              </div>
              <span className="tnum text-[11px] text-[#98A2B3] whitespace-nowrap">
                {fmtDate(m.created_at)}
              </span>
              <div className="flex justify-end">
                <UnmapButton mappingId={m.mapping_id} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function fmtSignedPct(pct: number): string {
  if (Math.abs(pct) < 0.05) return "0.0%";
  return `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

function SortHeader({
  label,
  active,
  dir,
  align = "left",
  onClick,
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  align?: "left" | "right";
  onClick: () => void;
}) {
  const Icon = active ? (dir === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`group inline-flex items-center gap-1.5 ${
        align === "right" ? "justify-end" : ""
      } transition-colors ${
        active
          ? "text-[#EA580C]"
          : "text-[#667085] hover:text-[#101828]"
      }`}
    >
      <span>{label}</span>
      <Icon
        className={`w-3 h-3 shrink-0 ${
          active ? "opacity-100" : "opacity-40 group-hover:opacity-80"
        }`}
        strokeWidth={2.5}
      />
    </button>
  );
}

function StatCard({
  label,
  value,
  sub,
  tone,
  active,
  onClick,
}: {
  label: string;
  value: number;
  sub?: string;
  tone: "neutral" | "good" | "bad" | "warn";
  active?: boolean;
  onClick?: () => void;
}) {
  const toneStyles = {
    neutral: { fg: "#101828", accent: "#667085", ring: "#D0D5DD" },
    good: { fg: "#067647", accent: "#067647", ring: "#ABEFC6" },
    bad: { fg: "#B42318", accent: "#B42318", ring: "#FECDCA" },
    warn: { fg: "#B54708", accent: "#B54708", ring: "#F6D28E" },
  } as const;
  const s = toneStyles[tone];
  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-left bg-white border rounded-[12px] px-4 py-3 transition-all ${
        active
          ? "border-[#EA580C] ring-2 ring-[#FFEDD5]"
          : "border-[#E4E7EC] hover:border-[#D0D5DD] hover:shadow-sm"
      }`}
      style={active ? undefined : { borderColor: undefined }}
    >
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-[#667085]">
        {label}
      </div>
      <div
        className="tnum text-[26px] font-bold tracking-[-0.02em] mt-1"
        style={{ color: s.fg }}
      >
        {value}
      </div>
      {sub && (
        <div className="text-[11px] mt-0.5" style={{ color: s.accent }}>
          {sub}
        </div>
      )}
    </button>
  );
}
