"use client";

import Link from "next/link";
import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Check,
  Loader2,
  Search,
  X,
} from "lucide-react";
import { API_BASE_PUBLIC, type ReviewItem } from "@/lib/api";
import { fmtMoney, fmtBasis, fmtAED } from "@/lib/format";
import { VerdictBadge } from "@/components/VerdictBadge";
import { RaynaProductLink } from "@/components/RaynaProductLink";
import { SearchableSelect } from "@/components/SearchableSelect";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";

type ReasonFilter = "all" | "low_conf" | "basis";
type SortKey = "product" | "seller" | "verdict" | "confidence" | "rayna" | "competitor";
type SortDir = "asc" | "desc";

function hasLowConf(item: ReviewItem): boolean {
  return item.confidence < 0.7;
}

function hasBasisMismatch(item: ReviewItem): boolean {
  return (
    item.rayna_basis !== item.competitor_basis &&
    item.rayna_basis !== "unknown" &&
    item.competitor_basis !== "unknown"
  );
}

export function ReviewQueueTable({ items }: { items: ReviewItem[] }) {
  const router = useRouter();
  const toast = useToast();
  const [, startTransition] = useTransition();

  const [q, setQ] = useState("");
  const [country, setCountry] = useState("all");
  const [city, setCity] = useState("all");
  const [seller, setSeller] = useState("all");
  const [reason, setReason] = useState<ReasonFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("confidence");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [pending, setPending] = useState<
    | { kind: "approve" | "reject"; item: ReviewItem }
    | null
  >(null);

  const countries = useMemo(() => {
    const s = new Set<string>();
    items.forEach((r) => {
      if (r.product_country) s.add(r.product_country);
    });
    return Array.from(s).sort();
  }, [items]);

  const cities = useMemo(() => {
    const s = new Set<string>();
    items.forEach((r) => {
      if (!r.product_city) return;
      if (country !== "all" && r.product_country !== country) return;
      s.add(r.product_city);
    });
    return Array.from(s).sort();
  }, [items, country]);

  const sellers = useMemo(() => {
    const s = new Set<string>();
    items.forEach((r) => s.add(r.seller_domain));
    return Array.from(s).sort();
  }, [items]);

  const nLowConf = items.filter(hasLowConf).length;
  const nBasis = items.filter(hasBasisMismatch).length;

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const rows = items.filter((r) => {
      if (country !== "all" && r.product_country !== country) return false;
      if (city !== "all" && r.product_city !== city) return false;
      if (seller !== "all" && r.seller_domain !== seller) return false;
      if (reason === "low_conf" && !hasLowConf(r)) return false;
      if (reason === "basis" && !hasBasisMismatch(r)) return false;
      if (needle) {
        const hay =
          `${r.product_name} ${r.rayna_option_name} ${r.competitor_option_name} ${r.seller_domain}`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });

    const dir = sortDir === "asc" ? 1 : -1;
    const cmpStr = (a: string, b: string) =>
      a.localeCompare(b, undefined, { sensitivity: "base" });
    const verdictOrder: Record<string, number> = {
      identical: 0,
      near: 1,
      different: 2,
    };

    rows.sort((A, B) => {
      switch (sortKey) {
        case "product":
          return cmpStr(A.product_name, B.product_name) * dir;
        case "seller":
          return cmpStr(A.seller_domain, B.seller_domain) * dir;
        case "verdict":
          return ((verdictOrder[A.verdict] ?? 9) - (verdictOrder[B.verdict] ?? 9)) * dir;
        case "rayna": {
          const a = A.rayna_price ?? null;
          const b = B.rayna_price ?? null;
          if (a == null && b == null) return 0;
          if (a == null) return 1;
          if (b == null) return -1;
          return (a - b) * dir;
        }
        case "competitor": {
          const a = A.competitor_price ?? null;
          const b = B.competitor_price ?? null;
          if (a == null && b == null) return 0;
          if (a == null) return 1;
          if (b == null) return -1;
          return (a - b) * dir;
        }
        case "confidence":
        default:
          return (A.confidence - B.confidence) * dir;
      }
    });

    return rows;
  }, [items, q, country, city, seller, reason, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      const numeric: SortKey[] = ["confidence", "rayna", "competitor"];
      setSortDir(numeric.includes(key) ? "asc" : "asc");
    }
  }

  async function runDecision(item: ReviewItem, approve: boolean) {
    if (busyId != null) return;
    setBusyId(item.mapping_id);
    try {
      const r = await fetch(
        `${API_BASE_PUBLIC}/api/mappings/${item.mapping_id}/review`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approve }),
        },
      );
      if (!r.ok) {
        let detail = `Review action failed (${r.status})`;
        try {
          const body = await r.json();
          if (body?.detail) detail = body.detail;
        } catch {
          /* not json */
        }
        toast.error(detail);
        return;
      }
      toast.success(approve ? "Approved" : "Rejected");
      setPending(null);
      startTransition(() => router.refresh());
    } finally {
      setBusyId(null);
    }
  }

  const activeFilter =
    !!q ||
    country !== "all" ||
    city !== "all" ||
    seller !== "all" ||
    reason !== "all";

  return (
    <>
      {/* Stat strip */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <StatCard
          label="In queue"
          value={items.length}
          sub="awaiting review"
          tone="neutral"
          active={reason === "all"}
          onClick={() => setReason("all")}
        />
        <StatCard
          label="Low confidence"
          value={nLowConf}
          sub="< 0.70 confidence"
          tone="warn"
          active={reason === "low_conf"}
          onClick={() => setReason(reason === "low_conf" ? "all" : "low_conf")}
        />
        <StatCard
          label="Basis mismatch"
          value={nBasis}
          sub="pricing basis differs"
          tone="bad"
          active={reason === "basis"}
          onClick={() => setReason(reason === "basis" ? "all" : "basis")}
        />
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="relative flex-1 min-w-[240px] max-w-[380px]">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-[#98A2B3]" />
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search product, option, or seller"
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
              setCountry("all");
              setCity("all");
              setSeller("all");
              setReason("all");
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
            {filtered.length}
          </span>{" "}
          of {items.length}
        </span>
      </div>

      {/* Table */}
      <div className="bg-white border border-[#E4E7EC] rounded-[10px] overflow-hidden">
        <div className="grid grid-cols-[1.3fr_1.7fr_1.2fr_1.7fr_0.9fr_0.9fr_0.9fr_1.8fr_150px] gap-3 px-5 py-[11px] bg-[#F9FAFB] border-b border-[#E4E7EC] text-[11px] font-semibold tracking-[0.04em] uppercase text-[#98A2B3]">
          <SortHeader
            label="Product"
            active={sortKey === "product"}
            dir={sortDir}
            onClick={() => toggleSort("product")}
          />
          <span>Rayna option</span>
          <SortHeader
            label="Seller"
            active={sortKey === "seller"}
            dir={sortDir}
            onClick={() => toggleSort("seller")}
          />
          <span>Competitor option</span>
          <SortHeader
            label="Verdict"
            active={sortKey === "verdict"}
            dir={sortDir}
            onClick={() => toggleSort("verdict")}
          />
          <SortHeader
            label="Rayna"
            align="right"
            active={sortKey === "rayna"}
            dir={sortDir}
            onClick={() => toggleSort("rayna")}
          />
          <SortHeader
            label="Competitor"
            align="right"
            active={sortKey === "competitor"}
            dir={sortDir}
            onClick={() => toggleSort("competitor")}
          />
          <span>Why review</span>
          <span className="text-right">Actions</span>
        </div>

        {filtered.length === 0 ? (
          <div className="px-5 py-16 text-center text-[13px] text-[#98A2B3]">
            No items match this filter.
          </div>
        ) : (
          <div className="divide-y divide-[#F1F2F4]">
            {filtered.map((item) => {
              const reasons: string[] = [];
              if (hasLowConf(item))
                reasons.push(`conf ${item.confidence.toFixed(2)}`);
              if (hasBasisMismatch(item))
                reasons.push(
                  `basis: ${fmtBasis(item.rayna_basis)} vs ${fmtBasis(item.competitor_basis)}`,
                );

              // Deep-link into the mapping workspace with this pair pre-selected.
              const workspaceHref = item.rayna_option_id
                ? `/?country=${encodeURIComponent(item.product_country ?? "")}&city=${encodeURIComponent(item.product_city ?? "")}&productId=${item.product_id}&raynaOptionId=${item.rayna_option_id}`
                : `/comparison/product/${item.product_id}`;
              const isBusy = busyId === item.mapping_id;

              return (
                <div
                  key={item.mapping_id}
                  className="grid grid-cols-[1.3fr_1.7fr_1.2fr_1.7fr_0.9fr_0.9fr_0.9fr_1.8fr_150px] gap-3 px-5 py-3.5 items-center hover:bg-[#F9FAFB] transition-colors"
                >
                  <Link
                    href={workspaceHref}
                    className="text-[12.5px] font-semibold text-[#EA580C] hover:text-[#C2410C] truncate"
                    title={`Open ${item.product_name} in mapping workspace`}
                  >
                    {item.product_name}
                    <RaynaProductLink url={item.product_url} name={item.product_name} className="ml-1.5 align-middle" />
                  </Link>
                  <div className="min-w-0">
                    <div className="text-[12.5px] text-[#101828] line-clamp-2 leading-snug">
                      {item.rayna_option_name}
                    </div>
                    <div className="text-[10.5px] font-mono text-[#98A2B3] mt-1">
                      {fmtBasis(item.rayna_basis)}
                    </div>
                  </div>
                  <span className="text-[12.5px] font-mono text-[#344054] truncate">
                    {item.seller_domain}
                  </span>
                  <div className="min-w-0">
                    <div className="text-[12.5px] text-[#101828] line-clamp-2 leading-snug">
                      {item.competitor_option_name}
                    </div>
                    <div className="text-[10.5px] font-mono text-[#98A2B3] mt-1">
                      {fmtBasis(item.competitor_basis)}
                    </div>
                  </div>
                  <VerdictBadge
                    verdict={item.verdict as "identical" | "near" | "different"}
                    confidence={item.confidence}
                  />
                  <span className="tnum text-right text-[12.5px] font-semibold text-[#101828] whitespace-nowrap">
                    {fmtMoney(item.rayna_price, item.rayna_currency)}
                  </span>
                  <div className="text-right whitespace-nowrap">
                    <div className="tnum text-[12.5px] font-semibold text-[#101828]">
                      {fmtAED(item.competitor_price, item.competitor_currency)}
                    </div>
                    {item.competitor_price != null &&
                      (item.competitor_currency || "AED").toUpperCase() !==
                        "AED" && (
                        <div className="tnum text-[10px] text-[#98A2B3]">
                          {fmtMoney(item.competitor_price, item.competitor_currency)}
                        </div>
                      )}
                  </div>
                  <div className="text-[11.5px] text-[#475467] min-w-0">
                    <div className="flex flex-wrap gap-1 mb-1">
                      {reasons.map((r) => (
                        <span
                          key={r}
                          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-[4px] bg-[#FBF1DE] text-[#9A6510] text-[10px] font-semibold border border-[#EFD8A6]"
                        >
                          <AlertTriangle className="w-3 h-3" />
                          {r}
                        </span>
                      ))}
                    </div>
                    <div className="italic text-[#98A2B3] leading-snug line-clamp-2">
                      {item.diff_notes}
                    </div>
                  </div>
                  <div className="flex items-center justify-end gap-1">
                    <button
                      type="button"
                      onClick={() => setPending({ kind: "approve", item })}
                      disabled={isBusy}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded-[6px] text-[11.5px] font-semibold text-[#067647] border border-[#ABEFC6] bg-[#ECFDF3] hover:bg-[#D1FADF] disabled:opacity-50 transition"
                    >
                      {isBusy ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Check className="w-3.5 h-3.5" />
                      )}
                      Approve
                    </button>
                    <button
                      type="button"
                      onClick={() => setPending({ kind: "reject", item })}
                      disabled={isBusy}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded-[6px] text-[11.5px] font-semibold text-[#B42318] border border-[#FECDCA] bg-[#FEE4E2] hover:bg-[#FECDCA] disabled:opacity-50 transition"
                    >
                      <X className="w-3.5 h-3.5" />
                      Reject
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={pending?.kind === "approve"}
        title="Approve this mapping?"
        body={
          pending?.kind === "approve" ? (
            <PairPreview item={pending.item} />
          ) : null
        }
        confirmLabel="Approve"
        busy={busyId != null}
        onConfirm={() =>
          pending?.kind === "approve" && runDecision(pending.item, true)
        }
        onCancel={() => busyId == null && setPending(null)}
      />

      <ConfirmDialog
        open={pending?.kind === "reject"}
        title="Reject this mapping?"
        danger
        body={
          pending?.kind === "reject" ? (
            <div className="space-y-2">
              <div>
                This deletes the mapping. The competitor option row stays in the
                workspace so it can be remapped elsewhere.
              </div>
              <PairPreview item={pending.item} />
            </div>
          ) : null
        }
        confirmLabel="Reject"
        busy={busyId != null}
        onConfirm={() =>
          pending?.kind === "reject" && runDecision(pending.item, false)
        }
        onCancel={() => busyId == null && setPending(null)}
      />
    </>
  );
}

function PairPreview({ item }: { item: ReviewItem }) {
  return (
    <div className="rounded-[8px] bg-[#F9FAFB] border border-[#E4E7EC] px-3 py-2 space-y-1.5">
      <div>
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.05em] text-[#98A2B3]">
          Rayna
        </span>
        <div className="text-[13px] font-semibold text-[#101828] leading-snug">
          {item.rayna_option_name}
        </div>
      </div>
      <div>
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.05em] text-[#98A2B3]">
          Competitor
          <span className="ml-1 font-mono normal-case text-[#98A2B3]">
            · {item.seller_domain}
          </span>
        </span>
        <div className="text-[13px] font-semibold text-[#101828] leading-snug">
          {item.competitor_option_name}
        </div>
      </div>
    </div>
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
    neutral: { fg: "#101828", accent: "#667085" },
    good: { fg: "#067647", accent: "#067647" },
    bad: { fg: "#B42318", accent: "#B42318" },
    warn: { fg: "#B54708", accent: "#B54708" },
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
        active ? "text-[#EA580C]" : "text-[#98A2B3] hover:text-[#344054]"
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
