"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Search, X } from "lucide-react";
import { SearchableSelect } from "@/components/SearchableSelect";
import type { DashboardStat } from "@/lib/api";
import { fmtPercent, fmtAED } from "@/lib/format";

type PositionKind = "leader" | "over" | "match" | "none";
type PositionFilter = "all" | PositionKind;

interface PositionInfo {
  kind: PositionKind;
  label: string;
  color: string;
  bg: string;
  border: string;
}

function classifyPosition(stat: DashboardStat): PositionInfo {
  const c = stat.cheapest_competitor;
  if (!c) {
    return {
      kind: "none",
      label: "No match yet",
      color: "#7A7F88",
      bg: "#F2F3F5",
      border: "#E2E3E7",
    };
  }
  const pct = c.gap_pct;
  if (pct > 1) {
    return {
      kind: "leader",
      label: `Cheapest · ${fmtPercent(Math.abs(pct))} under`,
      color: "#C2410C",
      bg: "#FFF4ED",
      border: "#FDBA74",
    };
  }
  if (pct < -1) {
    return {
      kind: "over",
      label: `${fmtPercent(Math.abs(pct))} over market`,
      color: "#B5342C",
      bg: "#FBEAE8",
      border: "#F1C7C2",
    };
  }
  return {
    kind: "match",
    label: "Matched at market",
    color: "#9A6510",
    bg: "#FBF1DE",
    border: "#EFD8A6",
  };
}

function emojiFor(name: string): string {
  const n = name.toLowerCase();
  if (n.includes("burj")) return "🌆";
  if (n.includes("desert") || n.includes("dune")) return "🏜";
  if (n.includes("dinner")) return "🍽";
  if (n.includes("fish")) return "🎣";
  if (n.includes("camel")) return "🐪";
  if (n.includes("city tour")) return "🚌";
  if (n.includes("yacht")) return "⛵";
  if (n.includes("sharjah")) return "🕌";
  if (n.includes("shopping")) return "🛍";
  return "📍";
}

type SortKey =
  | "product"
  | "options"
  | "sellers"
  | "position"
  | "cheapest";
type SortDir = "asc" | "desc";

export function ComparisonProductsTable({ stats }: { stats: DashboardStat[] }) {
  const [q, setQ] = useState("");
  const [country, setCountry] = useState<string>("all");
  const [city, setCity] = useState<string>("all");
  const [position, setPosition] = useState<PositionFilter>("all");
  const [onlyMapped, setOnlyMapped] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("position");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const countries = useMemo(() => {
    const s = new Set<string>();
    stats.forEach((r) => {
      if (r.product.country) s.add(r.product.country);
    });
    return Array.from(s).sort();
  }, [stats]);

  const cities = useMemo(() => {
    const s = new Set<string>();
    stats.forEach((r) => {
      if (!r.product.city) return;
      if (country !== "all" && r.product.country !== country) return;
      s.add(r.product.city);
    });
    return Array.from(s).sort();
  }, [stats, country]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const rows = stats
      .map((s) => ({ s, pos: classifyPosition(s) }))
      .filter(({ s, pos }) => {
        if (country !== "all" && s.product.country !== country) return false;
        if (city !== "all" && s.product.city !== city) return false;
        if (position !== "all" && pos.kind !== position) return false;
        if (onlyMapped && !s.cheapest_competitor) return false;
        if (needle) {
          const hay =
            `${s.product.name} ${s.product.city ?? ""} ${s.product.country ?? ""} ${s.product.type ?? ""}`.toLowerCase();
          if (!hay.includes(needle)) return false;
        }
        return true;
      });

    const dir = sortDir === "asc" ? 1 : -1;
    const cmpStr = (a: string, b: string) =>
      a.localeCompare(b, undefined, { sensitivity: "base" });
    // Ranking for the "position" column: leader (we win) first, then market
    // parity, then over-market, then no-match. Ascending = best-for-us first.
    const posRank: Record<PositionKind, number> = {
      leader: 0,
      match: 1,
      over: 2,
      none: 3,
    };

    rows.sort((A, B) => {
      switch (sortKey) {
        case "product":
          return cmpStr(A.s.product.name, B.s.product.name) * dir;
        case "options":
          return (A.s.option_count - B.s.option_count) * dir;
        case "sellers":
          return (A.s.seller_count - B.s.seller_count) * dir;
        case "cheapest": {
          const a = A.s.cheapest_competitor?.price ?? null;
          const b = B.s.cheapest_competitor?.price ?? null;
          if (a == null && b == null) return 0;
          if (a == null) return 1;
          if (b == null) return -1;
          return (a - b) * dir;
        }
        case "position":
        default:
          return (posRank[A.pos.kind] - posRank[B.pos.kind]) * dir;
      }
    });

    return rows;
  }, [stats, q, country, city, position, onlyMapped, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      const numeric: SortKey[] = ["options", "sellers", "cheapest"];
      setSortDir(numeric.includes(key) ? "desc" : "asc");
    }
  }

  const activeFilter =
    !!q ||
    country !== "all" ||
    city !== "all" ||
    position !== "all" ||
    onlyMapped;

  return (
    <>
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <div className="flex items-baseline gap-2.5">
          <h2 className="text-[16px] font-semibold -tracking-[0.01em]">
            Tracked products
          </h2>
          <span className="tnum text-[12.5px] text-[#98A2B3]">
            {filtered.length} of {stats.length}
          </span>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="relative flex-1 min-w-[240px] max-w-[380px]">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-[#98A2B3]" />
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search product name, city, or type"
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

        <div className="inline-flex items-center border border-[#D0D5DD] rounded-[9px] bg-white overflow-hidden">
          {(
            [
              ["all", "All"],
              ["leader", "Cheapest"],
              ["match", "Match"],
              ["over", "Over"],
              ["none", "No match"],
            ] as [PositionFilter, string][]
          ).map(([k, label], i) => {
            const active = position === k;
            return (
              <button
                key={k}
                type="button"
                onClick={() => setPosition(k)}
                className={`px-2.5 py-1.5 text-[11.5px] font-semibold transition-colors ${
                  i > 0 ? "border-l border-[#E4E7EC]" : ""
                } ${
                  active
                    ? "bg-[#FFF4ED] text-[#C2410C]"
                    : "text-[#667085] hover:text-[#101828] hover:bg-[#F9FAFB]"
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>

        <label className="inline-flex items-center gap-1.5 text-[12px] text-[#475467] cursor-pointer select-none">
          <input
            type="checkbox"
            checked={onlyMapped}
            onChange={(e) => setOnlyMapped(e.target.checked)}
            className="w-3.5 h-3.5 accent-[#EA580C]"
          />
          Only with competitor
        </label>

        {activeFilter && (
          <button
            type="button"
            onClick={() => {
              setQ("");
              setCountry("all");
              setCity("all");
              setPosition("all");
              setOnlyMapped(false);
            }}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-[12px] font-semibold text-[#475467] hover:text-[#101828] hover:bg-[#F2F4F7] rounded-[7px] transition"
          >
            <X className="w-3.5 h-3.5" />
            Clear
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-white border border-[#E4E7EC] rounded-[10px] overflow-hidden">
        <div className="grid grid-cols-[2.4fr_0.8fr_1fr_1.4fr_1.1fr] gap-3 px-5 py-[11px] bg-[#F9FAFB] border-b border-[#E4E7EC] text-[11px] font-semibold tracking-[0.04em] uppercase text-[#98A2B3]">
          <SortHeader
            label="Product"
            active={sortKey === "product"}
            dir={sortDir}
            onClick={() => toggleSort("product")}
          />
          <SortHeader
            label="Options"
            align="center"
            active={sortKey === "options"}
            dir={sortDir}
            onClick={() => toggleSort("options")}
          />
          <SortHeader
            label="Sellers"
            align="center"
            active={sortKey === "sellers"}
            dir={sortDir}
            onClick={() => toggleSort("sellers")}
          />
          <SortHeader
            label="Price position"
            active={sortKey === "position"}
            dir={sortDir}
            onClick={() => toggleSort("position")}
          />
          <SortHeader
            label="Cheapest competitor"
            align="right"
            active={sortKey === "cheapest"}
            dir={sortDir}
            onClick={() => toggleSort("cheapest")}
          />
        </div>

        {filtered.length === 0 ? (
          <div className="px-5 py-16 text-center text-[13px] text-[#98A2B3]">
            No products match this filter.
          </div>
        ) : (
          filtered.map(({ s, pos }) => (
            <Link
              key={s.product.id}
              href={`/comparison/product/${s.product.id}`}
              className="grid grid-cols-[2.4fr_0.8fr_1fr_1.4fr_1.1fr] gap-3 items-center px-5 py-[14px] border-b border-[#F2F4F7] last:border-b-0 hover:bg-[#F9FAFB] transition-colors"
            >
              <div className="flex items-center gap-[11px] min-w-0">
                <span className="w-[34px] h-[34px] shrink-0 rounded-[8px] bg-[#FFF4ED] border border-[#F1DFB4] grid place-items-center text-[16px]">
                  {emojiFor(s.product.name)}
                </span>
                <div className="min-w-0">
                  <div className="text-[13.5px] font-semibold text-[#101828] truncate">
                    {s.product.name}
                  </div>
                  <div className="text-[11.5px] text-[#98A2B3] truncate">
                    {s.product.type ?? "Activities"}
                    {s.product.city ? ` · ${s.product.city}` : ""}
                  </div>
                </div>
              </div>
              <span className="tnum text-center text-[13px] font-medium text-[#475467]">
                {s.option_count}
              </span>
              <span className="tnum text-center text-[13px] font-medium text-[#475467]">
                {s.seller_count}
              </span>
              <div>
                <span
                  className="inline-flex items-center gap-1.5 px-2.5 py-[3px] rounded-[6px] text-[11.5px] font-semibold border"
                  style={{
                    background: pos.bg,
                    color: pos.color,
                    borderColor: pos.border,
                  }}
                >
                  <span
                    className="w-[6px] h-[6px] rounded-full"
                    style={{ background: pos.color }}
                  />
                  {pos.label}
                </span>
              </div>
              <span className="tnum text-right text-[11.5px] text-[#98A2B3]">
                {s.cheapest_competitor
                  ? `${fmtAED(s.cheapest_competitor.price, s.cheapest_competitor.currency)} on ${s.cheapest_competitor.domain}`
                  : "—"}
              </span>
            </Link>
          ))
        )}
      </div>
    </>
  );
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
  align?: "left" | "center" | "right";
  onClick: () => void;
}) {
  const Icon = active ? (dir === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
  const alignCls =
    align === "right"
      ? "justify-end"
      : align === "center"
      ? "justify-center"
      : "";
  return (
    <button
      type="button"
      onClick={onClick}
      className={`group inline-flex items-center gap-1.5 ${alignCls} transition-colors ${
        active
          ? "text-[#EA580C]"
          : "text-[#98A2B3] hover:text-[#344054]"
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
