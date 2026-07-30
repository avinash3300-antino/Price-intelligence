import Link from "next/link";
import { AlertTriangle, ExternalLink } from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import { getMapped, type MappedItem } from "@/lib/api";
import { fmtMoney, fmtBasis, fmtAED, toAED } from "@/lib/format";
import { UnmapButton } from "@/components/UnmapButton";
import { MappedDatePill } from "@/components/MappedDatePill";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{ date?: string }>;

function isValidIsoDate(s: string | undefined): s is string {
  return !!s && /^\d{4}-\d{2}-\d{2}$/.test(s);
}

interface GapDisplay {
  kind: "leader" | "over" | "match" | "unknown" | "basis_mismatch";
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
  // diff > 0  →  competitor pricier  →  WE WIN  →  green ▼
  if (diff > 0) {
    return {
      kind: "leader",
      label: `▼ −${pct.toFixed(1)}%`,
      className: "text-[#067647] font-semibold",
    };
  }
  // diff < 0  →  we're pricier  →  OVER MARKET  →  red ▲
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

export default async function MappedPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const sp = await searchParams;
  const today = new Date().toISOString().slice(0, 10);
  const date = isValidIsoDate(sp.date) ? sp.date : today;
  const items = await getMapped(date);

  const dateLabel = new Date(date + "T00:00:00").toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });

  // Roll-up stats for the strip
  const gaps = items.map(computeGap);
  const nLeader = gaps.filter((g) => g.kind === "leader").length;
  const nOver = gaps.filter((g) => g.kind === "over").length;
  const nParity = gaps.filter((g) => g.kind === "match").length;
  const nBasis = gaps.filter((g) => g.kind === "basis_mismatch").length;

  return (
    <AppLayout>
      <div className="max-w-[1480px] mx-auto px-8 py-7 w-full">
        {/* Page title + date */}
        <div className="mb-6 flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-[24px] font-bold tracking-[-0.02em] text-[#101828]">
              Mapped pairs
            </h1>
            <p className="text-[13px] text-[#667085] mt-1">
              Confirmed Rayna ↔ competitor links, ready to compare against the
              market for{" "}
              <span className="text-[#EA580C] font-semibold">{dateLabel}</span>.
            </p>
          </div>
          <MappedDatePill value={date} />
        </div>

        {items.length === 0 ? (
          <div className="bg-white border border-dashed border-[#D0D5DD] rounded-[12px] px-8 py-20 text-center">
            <div className="text-[15px] font-semibold text-[#344054] mb-1.5">
              Nothing mapped yet
            </div>
            <div className="text-[13px] text-[#667085] mb-5">
              Head to the Mapping tab to link Rayna products to competitor
              options.
            </div>
            <Link
              href="/"
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-[9px] text-[13px] font-semibold bg-[#EA580C] text-white hover:bg-[#C2410C] transition-colors"
            >
              Go to mapping
            </Link>
          </div>
        ) : (
          <>
            {/* Stat strip */}
            <div className="grid grid-cols-4 gap-3 mb-4">
              <StatCard label="Mappings" value={items.length} tone="neutral" />
              <StatCard
                label="Price leader"
                value={nLeader}
                sub={nLeader === 1 ? "product" : "products"}
                tone="good"
              />
              <StatCard
                label="Over market"
                value={nOver}
                sub={nOver === 1 ? "product" : "products"}
                tone="bad"
              />
              <StatCard
                label={nBasis > 0 ? "Basis mismatch" : "At parity"}
                value={nBasis > 0 ? nBasis : nParity}
                sub={nBasis > 0 ? "needs review" : "at market"}
                tone={nBasis > 0 ? "warn" : "neutral"}
              />
            </div>

            {/* Single unified table */}
            <div className="bg-white border border-[#E4E7EC] rounded-[12px] overflow-hidden">
              <div className="grid grid-cols-[2.2fr_1.2fr_2.2fr_0.9fr_0.9fr_0.8fr_0.9fr_70px] gap-3 px-5 py-3 bg-[#F9FAFB] border-b border-[#E4E7EC] text-[10.5px] font-semibold tracking-[0.05em] uppercase text-[#667085] sticky top-0 z-10">
                <span>Rayna option</span>
                <span>Seller</span>
                <span>Competitor option</span>
                <span className="text-right">Rayna</span>
                <span className="text-right">Competitor</span>
                <span className="text-right">Gap</span>
                <span>Mapped</span>
                <span />
              </div>
              <div className="divide-y divide-[#F2F4F7]">
                {items.map((m, i) => {
                  const gap = gaps[i];
                  return (
                    <div
                      key={m.mapping_id}
                      className="grid grid-cols-[2.2fr_1.2fr_2.2fr_0.9fr_0.9fr_0.8fr_0.9fr_70px] gap-3 px-5 py-4 hover:bg-[#F9FAFB] transition-colors items-center"
                    >
                      {/* Rayna option (with product subtitle) */}
                      <div className="min-w-0">
                        <div className="text-[13px] font-semibold text-[#101828] line-clamp-2 leading-snug">
                          {m.rayna_option_name}
                        </div>
                        <div className="text-[11px] text-[#98A2B3] mt-1 flex items-center gap-1.5">
                          <span className="truncate">{m.product_name}</span>
                          <span className="text-[#D0D5DD]">·</span>
                          <span className="font-mono">
                            {fmtBasis(m.rayna_basis)}
                          </span>
                        </div>
                      </div>

                      {/* Seller domain (link out) */}
                      <a
                        href={m.listing_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[12.5px] font-mono text-[#344054] hover:text-[#EA580C] inline-flex items-center gap-1.5 truncate"
                      >
                        {m.seller_domain}
                        <ExternalLink className="w-3 h-3 opacity-50 shrink-0" />
                      </a>

                      {/* Competitor option */}
                      <div className="min-w-0">
                        <div className="text-[13px] text-[#101828] line-clamp-2 leading-snug">
                          {m.competitor_option_name}
                        </div>
                        <div className="text-[11px] text-[#98A2B3] font-mono mt-1">
                          {fmtBasis(m.competitor_basis)}
                        </div>
                      </div>

                      {/* Rayna price */}
                      <div className="text-right whitespace-nowrap">
                        <div className="tnum text-[13px] font-semibold text-[#101828]">
                          {fmtAED(m.rayna_price, m.rayna_currency)}
                        </div>
                        {m.rayna_date_price_source === "default" && (
                          <div
                            title="No observation for this date; showing default variant price"
                            className="inline-flex items-center gap-1 text-[9.5px] text-[#B54708] font-semibold mt-0.5"
                          >
                            <AlertTriangle className="w-3 h-3" />
                            default
                          </div>
                        )}
                      </div>

                      {/* Competitor price */}
                      <div className="text-right whitespace-nowrap">
                        <div className="tnum text-[13px] font-semibold text-[#101828]">
                          {fmtAED(m.competitor_price, m.competitor_currency)}
                        </div>
                        {m.competitor_price != null &&
                          (m.competitor_currency || "AED").toUpperCase() !==
                            "AED" && (
                            <div className="tnum text-[10.5px] text-[#98A2B3]">
                              {fmtMoney(
                                m.competitor_price,
                                m.competitor_currency,
                              )}
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

                      {/* Gap — colored red/green/grey with arrow */}
                      <div
                        className={`text-right whitespace-nowrap tnum text-[12.5px] ${gap.className}`}
                      >
                        {gap.label}
                      </div>

                      {/* Mapped-at timestamp */}
                      <span className="tnum text-[11px] text-[#98A2B3] whitespace-nowrap">
                        {fmtDate(m.created_at)}
                      </span>

                      {/* Unmap button */}
                      <div className="flex justify-end">
                        <UnmapButton mappingId={m.mapping_id} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Legend row */}
            <div className="mt-4 flex items-center gap-5 flex-wrap text-[11.5px] text-[#667085]">
              <span className="inline-flex items-center gap-1.5">
                <span className="text-[#067647] font-semibold tnum">▼ under</span>
                <span>Rayna is cheaper (we win)</span>
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="text-[#B42318] font-semibold tnum">▲ over</span>
                <span>Rayna is pricier (over market)</span>
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="text-[#475467] font-semibold tnum">= par</span>
                <span>within ±0.5 AED</span>
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="text-[#B54708] font-semibold">basis ⚠</span>
                <span>pricing bases differ — gap not directly comparable</span>
              </span>
            </div>
          </>
        )}
      </div>
    </AppLayout>
  );
}

function StatCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: number;
  sub?: string;
  tone: "neutral" | "good" | "bad" | "warn";
}) {
  const toneStyles = {
    neutral: { fg: "#101828", accent: "#667085" },
    good: { fg: "#067647", accent: "#067647" },
    bad: { fg: "#B42318", accent: "#B42318" },
    warn: { fg: "#B54708", accent: "#B54708" },
  } as const;
  const s = toneStyles[tone];
  return (
    <div className="bg-white border border-[#E4E7EC] rounded-[12px] px-4 py-3">
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
    </div>
  );
}
