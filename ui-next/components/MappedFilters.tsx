"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Award, ChevronLeft, ChevronRight, ExternalLink, Layers, Search, TrendingDown, TrendingUp, X } from "lucide-react";
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

const PAGE_SIZE_OPTIONS = [5, 10, 25, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 10;

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
  // Pagination is over option cards, not raw mapping rows, so a card's
  // sellers never get split across two pages.
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  const listTopRef = useRef<HTMLDivElement | null>(null);

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

  // Rearrange filtered so rows with the same Rayna option cluster together
  // (preserving first-encounter order from the outer sort). This lets the
  // hide-duplicates rendering below blank out repeated Rayna option cells
  // and draw a subtle group divider between distinct options — same table,
  // less repeated text.
  const grouped = useMemo(() => {
    const buckets = new Map<number, Array<{ m: MappedItem; gap: GapDisplay }>>();
    for (const row of filtered) {
      const arr = buckets.get(row.m.rayna_option_id);
      if (arr) arr.push(row);
      else buckets.set(row.m.rayna_option_id, [row]);
    }
    return Array.from(buckets.values()).flat();
  }, [filtered]);

  // Structured option-cards form of the same data: one entry per Rayna
  // option, with a header row + all its seller mappings. Order preserved
  // from `grouped` so the outer sort still decides which cards come first.
  const optionCards = useMemo(() => {
    const buckets = new Map<
      number,
      { header: MappedItem; rows: Array<{ m: MappedItem; gap: GapDisplay }> }
    >();
    for (const row of grouped) {
      const b = buckets.get(row.m.rayna_option_id);
      if (b) b.rows.push(row);
      else buckets.set(row.m.rayna_option_id, { header: row.m, rows: [row] });
    }
    return Array.from(buckets.values());
  }, [grouped]);

  // Any change to the filter/sort inputs invalidates the current page number,
  // so snap back to the first page rather than stranding the user on an
  // out-of-range page of a freshly narrowed result set.
  useEffect(() => {
    setPage(1);
  }, [q, seller, position, country, city, sortKey, sortDir, pageSize]);

  const totalPages = Math.max(1, Math.ceil(optionCards.length / pageSize));
  // Clamp instead of trusting `page`: items can shrink underneath us (an
  // unmap removes a card) between the effect above and this render.
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * pageSize;
  const pagedCards = optionCards.slice(pageStart, pageStart + pageSize);

  function goToPage(next: number) {
    const clamped = Math.min(Math.max(next, 1), totalPages);
    setPage(clamped);
    listTopRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

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

  // Aggregate insights: avg gap across comparable, biggest win, biggest gap,
  // seller-coverage leader (Rayna option with most sellers mapped).
  const insights = useMemo(() => {
    let sum = 0;
    let n = 0;
    let bestWin: { m: MappedItem; pct: number } | null = null;
    let worstGap: { m: MappedItem; pct: number } | null = null;
    const optCoverage = new Map<
      number,
      { count: number; m: MappedItem }
    >();
    for (const m of items) {
      // Coverage tally regardless of comparability
      const cur = optCoverage.get(m.rayna_option_id);
      if (cur) {
        cur.count += 1;
      } else {
        optCoverage.set(m.rayna_option_id, { count: 1, m });
      }
      if (m.rayna_basis !== m.competitor_basis) continue;
      const r = toAED(m.rayna_price, m.rayna_currency);
      const c = toAED(m.competitor_price, m.competitor_currency);
      if (r == null || c == null || r === 0) continue;
      const pct = ((c - r) / r) * 100;
      sum += pct;
      n += 1;
      if (pct > 0 && (!bestWin || pct > bestWin.pct)) {
        // competitor pricier → Rayna wins
        bestWin = { m, pct };
      }
      if (pct < 0 && (!worstGap || pct < worstGap.pct)) {
        // competitor cheaper → Rayna over-market
        worstGap = { m, pct };
      }
    }
    let coverageLeader: { count: number; m: MappedItem } | null = null;
    for (const v of optCoverage.values()) {
      if (!coverageLeader || v.count > coverageLeader.count) coverageLeader = v;
    }
    return {
      avgPct: n === 0 ? null : sum / n,
      nComparable: n,
      bestWin,
      worstGap,
      coverageLeader,
    };
  }, [items]);

  const activeFilter =
    !!q ||
    seller !== "all" ||
    position !== "all" ||
    country !== "all" ||
    city !== "all";

  return (
    <>
      {/* KPI strip — clickable, tinted backgrounds by tone. */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard
          label="Mappings"
          value={items.length}
          sub={items.length === 1 ? "confirmed link" : "confirmed links"}
          tone="neutral"
          icon={<Layers className="w-4 h-4" strokeWidth={2.5} />}
          active={position === "all"}
          onClick={() => setPosition("all")}
        />
        <StatCard
          label="Avg market gap"
          value={insights.avgPct == null ? "—" : `${insights.avgPct > 0 ? "+" : ""}${insights.avgPct.toFixed(1)}%`}
          sub={
            insights.avgPct == null
              ? "no comparable pairs"
              : insights.avgPct > 0
                ? "competitor is pricier on average"
                : "competitor is cheaper on average"
          }
          tone={
            insights.avgPct == null
              ? "neutral"
              : insights.avgPct > 5
                ? "good"
                : insights.avgPct < -5
                  ? "bad"
                  : "neutral"
          }
          icon={
            insights.avgPct != null && insights.avgPct > 0 ? (
              <TrendingUp className="w-4 h-4" strokeWidth={2.5} />
            ) : (
              <TrendingDown className="w-4 h-4" strokeWidth={2.5} />
            )
          }
        />
        <StatCard
          label="You win"
          value={nLeader}
          sub={nLeader === 1 ? "product cheaper" : "products cheaper"}
          tone="good"
          icon={<Award className="w-4 h-4" strokeWidth={2.5} />}
          active={position === "leader"}
          onClick={() =>
            setPosition(position === "leader" ? "all" : "leader")
          }
        />
        <StatCard
          label={nBasis > 0 ? "Over market · Basis ⚠" : "Over market"}
          value={nOver + (nBasis > 0 ? nBasis : 0)}
          sub={
            nBasis > 0
              ? `${nOver} pricier · ${nBasis} basis mismatch`
              : nOver === 1
                ? "product pricier"
                : "products pricier"
          }
          tone="bad"
          icon={<AlertTriangle className="w-4 h-4" strokeWidth={2.5} />}
          active={position === "over"}
          onClick={() => setPosition(position === "over" ? "all" : "over")}
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
          Showing <span className="font-semibold text-[#101828]">{filtered.length}</span>{" "}
          of {items.length}
        </span>
      </div>

      {/* Option cards — one per Rayna option, sellers listed underneath. */}
      <div ref={listTopRef} className="scroll-mt-6" />
      {optionCards.length === 0 ? (
        <div className="bg-white border border-[#E4E7EC] rounded-[12px] px-5 py-16 text-center text-[13px] text-[#98A2B3]">
          No mappings match this filter.
        </div>
      ) : (
        <>
          <div className="space-y-3">
            {pagedCards.map((g) => (
              <OptionCard key={g.header.rayna_option_id} group={g} />
            ))}
          </div>

          <Pagination
            page={currentPage}
            totalPages={totalPages}
            pageSize={pageSize}
            onPageSize={setPageSize}
            onPage={goToPage}
            rangeStart={pageStart + 1}
            rangeEnd={pageStart + pagedCards.length}
            total={optionCards.length}
          />
        </>
      )}
    </>
  );
}


/* ---------- Pagination ---------- */

// Compact page list: always show first/last, a window around the current
// page, and "…" for the elided stretches.
function pageWindow(page: number, totalPages: number): Array<number | "gap"> {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  const out: Array<number | "gap"> = [1];
  const from = Math.max(2, page - 1);
  const to = Math.min(totalPages - 1, page + 1);
  if (from > 2) out.push("gap");
  for (let i = from; i <= to; i++) out.push(i);
  if (to < totalPages - 1) out.push("gap");
  out.push(totalPages);
  return out;
}

function Pagination({
  page,
  totalPages,
  pageSize,
  onPageSize,
  onPage,
  rangeStart,
  rangeEnd,
  total,
}: {
  page: number;
  totalPages: number;
  pageSize: number;
  onPageSize: (n: number) => void;
  onPage: (n: number) => void;
  rangeStart: number;
  rangeEnd: number;
  total: number;
}) {
  const arrowCls =
    "inline-flex items-center gap-1 px-2.5 py-1.5 rounded-[8px] text-[12px] font-semibold border border-[#D0D5DD] bg-white text-[#344054] transition hover:border-[#EA580C] hover:text-[#EA580C] disabled:opacity-40 disabled:pointer-events-none";

  return (
    <div className="mt-4 flex items-center justify-between gap-4 flex-wrap">
      <div className="flex items-center gap-2 text-[12px] text-[#667085]">
        <span className="tnum">
          Options{" "}
          <span className="font-semibold text-[#101828]">
            {rangeStart}–{rangeEnd}
          </span>{" "}
          of <span className="font-semibold text-[#101828]">{total}</span>
        </span>
        <span className="text-[#D0D5DD]">·</span>
        <label className="flex items-center gap-1.5">
          <span>Per page</span>
          <select
            value={pageSize}
            onChange={(e) => onPageSize(Number(e.target.value))}
            className="tnum py-1 pl-2 pr-6 text-[12px] font-semibold bg-white border border-[#D0D5DD] rounded-[8px] outline-none focus:border-[#EA580C] focus:ring-2 focus:ring-[#FFEDD5] transition cursor-pointer"
          >
            {PAGE_SIZE_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>

      {totalPages > 1 && (
        <nav className="flex items-center gap-1.5" aria-label="Pagination">
          <button
            type="button"
            onClick={() => onPage(page - 1)}
            disabled={page <= 1}
            className={arrowCls}
            aria-label="Previous page"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
            Prev
          </button>

          {pageWindow(page, totalPages).map((p, i) =>
            p === "gap" ? (
              <span
                key={`gap-${i}`}
                className="px-1 text-[12px] text-[#98A2B3] select-none"
              >
                …
              </span>
            ) : (
              <button
                key={p}
                type="button"
                onClick={() => onPage(p)}
                aria-current={p === page ? "page" : undefined}
                className={`tnum min-w-[30px] px-2 py-1.5 rounded-[8px] text-[12px] font-semibold border transition ${
                  p === page
                    ? "border-[#EA580C] bg-[#FFF4ED] text-[#C2410C]"
                    : "border-[#D0D5DD] bg-white text-[#344054] hover:border-[#EA580C] hover:text-[#EA580C]"
                }`}
              >
                {p}
              </button>
            ),
          )}

          <button
            type="button"
            onClick={() => onPage(page + 1)}
            disabled={page >= totalPages}
            className={arrowCls}
            aria-label="Next page"
          >
            Next
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </nav>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  tone,
  icon,
  active,
  onClick,
}: {
  label: string;
  value: number | string;
  sub?: string;
  tone: "neutral" | "good" | "bad" | "warn";
  icon?: React.ReactNode;
  active?: boolean;
  onClick?: () => void;
}) {
  const toneStyles = {
    neutral: { fg: "#101828", accent: "#667085", tintBg: "#F8F9FB", iconBg: "#F2F4F7", iconFg: "#667085" },
    good:    { fg: "#067647", accent: "#067647", tintBg: "#F0FDF4", iconBg: "#DCFCE7", iconFg: "#059669" },
    bad:     { fg: "#B42318", accent: "#B42318", tintBg: "#FEF2F2", iconBg: "#FEE2E2", iconFg: "#DC2626" },
    warn:    { fg: "#B54708", accent: "#B54708", tintBg: "#FEFCE8", iconBg: "#FEF3C7", iconFg: "#B45309" },
  } as const;
  const s = toneStyles[tone];
  const clickable = !!onClick;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!clickable}
      className={`text-left border rounded-[14px] px-5 py-4 transition-all disabled:cursor-default ${
        active
          ? "border-[#EA580C] ring-2 ring-[#FFEDD5] bg-white"
          : `border-[#E4E7EC] ${clickable ? "hover:border-[#D0D5DD] hover:shadow-sm" : ""}`
      }`}
      style={{ background: active ? "#ffffff" : s.tintBg }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-[#667085]">
          {label}
        </div>
        {icon && (
          <span
            className="w-[26px] h-[26px] rounded-[8px] grid place-items-center shrink-0"
            style={{ background: s.iconBg, color: s.iconFg }}
          >
            {icon}
          </span>
        )}
      </div>
      <div
        className="tnum text-[28px] font-bold tracking-[-0.02em] mt-2 leading-tight"
        style={{ color: s.fg }}
      >
        {value}
      </div>
      {sub && (
        <div className="text-[11px] mt-1" style={{ color: s.accent }}>
          {sub}
        </div>
      )}
    </button>
  );
}

/* ---------- Insight card (biggest win / biggest gap / most coverage) ---------- */


/* ---------- Gap distribution card ---------- */


/* ---------- Seller coverage card ---------- */


/* ---------- Option card (per Rayna option, elevated card with price-position strip) ---------- */

function OptionCard({
  group,
}: {
  group: {
    header: MappedItem;
    rows: Array<{ m: MappedItem; gap: GapDisplay }>;
  };
}) {
  const { header, rows } = group;

  return (
    <div className="bg-white border border-[#E4E7EC] rounded-[12px] overflow-hidden">
      {/* Card header */}
      <div className="px-5 pt-4 pb-3 flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-bold text-[#101828] leading-snug">
            {header.rayna_option_name}
          </div>
          <div className="text-[11.5px] text-[#667085] mt-1 flex items-center gap-1.5 flex-wrap">
            <span className="truncate">{header.product_name}</span>
            <span className="text-[#D0D5DD]">·</span>
            <span className="font-mono">{fmtBasis(header.rayna_basis)}</span>
            <span className="text-[#D0D5DD]">·</span>
            <span className="tnum">
              {rows.length} seller{rows.length === 1 ? "" : "s"} mapped
            </span>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[#98A2B3]">
            Rayna price
          </div>
          <div className="tnum text-[24px] font-bold text-[#EA580C] tracking-tight leading-tight">
            {fmtAED(header.rayna_price, header.rayna_currency)}
          </div>
          {header.rayna_date_price_source === "default" && (
            <div
              title="No observation for this date; showing default variant price"
              className="inline-flex items-center gap-1 text-[9.5px] text-[#B54708] font-semibold mt-0.5"
            >
              <AlertTriangle className="w-3 h-3" />
              default
            </div>
          )}
        </div>
      </div>

      {/* Seller mappings list */}
      <div className="border-t border-[#F2F4F7]">
        {rows.map(({ m, gap }) => {
          return (
            <div
              key={m.mapping_id}
              className="grid grid-cols-[minmax(180px,1.5fr)_1fr_0.9fr_140px_70px] gap-3 px-5 py-3 hover:bg-[#F9FAFB] transition-colors items-center border-t border-[#F2F4F7] first:border-t-0"
            >
              <a
                href={m.listing_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 min-w-0 group"
                title={`Open ${m.seller_domain} listing (${m.competitor_option_name})`}
              >
                <span className="w-[26px] h-[26px] rounded-[7px] bg-[#FFF4ED] border border-[#FED7AA] text-[#C2410C] grid place-items-center text-[11px] font-bold shrink-0">
                  {m.seller_domain[0]?.toUpperCase() || "?"}
                </span>
                <span className="text-[13px] font-mono text-[#344054] group-hover:text-[#EA580C] truncate">
                  {m.seller_domain}
                </span>
                <ExternalLink className="w-3.5 h-3.5 opacity-40 shrink-0 group-hover:opacity-80" />
              </a>

              <div className="text-right whitespace-nowrap">
                <div className="tnum text-[14px] font-semibold text-[#101828]">
                  {fmtAED(m.competitor_price, m.competitor_currency)}
                </div>
                {m.competitor_price != null &&
                  (m.competitor_currency || "AED").toUpperCase() !== "AED" && (
                    <div className="tnum text-[10.5px] text-[#98A2B3]">
                      {fmtMoney(m.competitor_price, m.competitor_currency)}
                    </div>
                  )}
              </div>

              <GapPill gap={gap} />

              <span className="tnum text-[11px] text-[#98A2B3] whitespace-nowrap text-right">
                {fmtDate(m.created_at)}
              </span>

              <div className="flex justify-end">
                <UnmapButton mappingId={m.mapping_id} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}


/* ---------- Small pill wrapper for the gap column so it feels less like table text ---------- */
function GapPill({ gap }: { gap: GapDisplay }) {
  const styles = {
    leader:         { color: "#166534", bg: "#F0FDF4", border: "#BBF7D0" },
    over:           { color: "#991B1B", bg: "#FEF2F2", border: "#FECACA" },
    match:          { color: "#475467", bg: "#F2F4F7", border: "#E4E7EC" },
    unknown:        { color: "#98A2B3", bg: "#F9FAFB", border: "#E4E7EC" },
    basis_mismatch: { color: "#B54708", bg: "#FFFAEB", border: "#FEDF89" },
  } as const;
  const s = styles[gap.kind];
  return (
    <span
      className="inline-flex items-center justify-center px-2 py-[3px] rounded-full text-[11.5px] font-semibold tnum border w-fit ml-auto"
      style={{ color: s.color, background: s.bg, borderColor: s.border }}
    >
      {gap.label}
    </span>
  );
}
