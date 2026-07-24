import Link from "next/link";
import { AlertTriangle, ExternalLink } from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import { getMapped } from "@/lib/api";
import { fmtMoney, fmtBasis, fmtAED, toAED } from "@/lib/format";
import { UnmapButton } from "@/components/UnmapButton";
import { MappedDatePill } from "@/components/MappedDatePill";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{ date?: string }>;

function isValidIsoDate(s: string | undefined): s is string {
  return !!s && /^\d{4}-\d{2}-\d{2}$/.test(s);
}

function priceGap(rayna: number | null, comp: number | null): React.ReactNode {
  if (rayna == null || comp == null) return <span className="text-[#9AA0A8]">—</span>;
  const diff = comp - rayna;
  const pct = (diff / rayna) * 100;
  if (Math.abs(diff) < 0.5)
    return <span className="text-[#5C6069] text-xs">match</span>;
  if (diff > 0)
    return (
      <span className="tnum text-[#197A45] font-semibold text-xs">
        +{pct.toFixed(1)}%
      </span>
    );
  return (
    <span className="tnum text-[#B5342C] font-semibold text-xs">
      {pct.toFixed(1)}%
    </span>
  );
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
  // Default to today so we always show real per-date prices; user can
  // pick any other date via the pill.
  const today = new Date().toISOString().slice(0, 10);
  const date = isValidIsoDate(sp.date) ? sp.date : today;
  const items = await getMapped(date);

  const byProduct = new Map<number, { name: string; items: typeof items }>();
  for (const item of items) {
    if (!byProduct.has(item.product_id)) {
      byProduct.set(item.product_id, { name: item.product_name, items: [] });
    }
    byProduct.get(item.product_id)!.items.push(item);
  }

  const dateLabel = new Date(date + "T00:00:00").toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });

  return (
    <AppLayout
      title="Mapped products"
      subtitle="Manually confirmed Rayna ↔ competitor pairs"
    >
      <div className="max-w-[1480px] mx-auto px-8 py-7">
        <div className="mb-7 flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-[22px] font-semibold tracking-[-0.02em]">
              Mapped pairs
            </h1>
            <p className="text-[13.5px] text-[#8A8F98] mt-1">
              <span className="tnum text-[#3D424B] font-semibold">{items.length}</span>{" "}
              {items.length === 1 ? "mapping" : "mappings"} ready to compare against the
              market for{" "}
              <span className="text-[#0E6F6A] font-semibold">{dateLabel}</span>
            </p>
          </div>
          <MappedDatePill value={date} />
        </div>

        {items.length === 0 ? (
          <div className="bg-white border border-dashed border-[#D5D7DC] rounded-[14px] px-8 py-20 text-center">
            <div className="text-[15px] font-semibold text-[#3D424B] mb-1.5">
              Nothing mapped yet
            </div>
            <div className="text-[13px] text-[#8A8F98] mb-5">
              Head to the Mapping tab to link Rayna products to competitor options.
            </div>
            <Link
              href="/"
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-[10px] text-[13px] font-semibold bg-[#0E6F6A] text-white hover:bg-[#0B5853] transition-colors"
            >
              Go to mapping
            </Link>
          </div>
        ) : (
          <div className="space-y-7">
            {[...byProduct.entries()].map(([productId, group]) => (
              <section key={productId}>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-baseline gap-2">
                    <h2 className="text-[11px] font-semibold uppercase tracking-[0.09em] text-[#5C6069]">
                      {group.name}
                    </h2>
                    <span className="text-[11px] text-[#9AA0A8]">
                      · {group.items.length} mapping
                      {group.items.length === 1 ? "" : "s"}
                    </span>
                  </div>
                  <Link
                    href={`/?productId=${productId}`}
                    className="text-[12px] font-semibold text-[#0E6F6A] hover:text-[#0B5853]"
                  >
                    Open in mapping →
                  </Link>
                </div>
                <div className="rounded-[13px] border border-[#EBECEF] bg-white overflow-hidden">
                  <div className="grid grid-cols-[2fr_1.4fr_2fr_0.8fr_0.8fr_0.7fr_0.8fr_60px] gap-3 px-5 py-[11px] bg-[#FAFBFC] border-b border-[#EBECEF] text-[10.5px] font-semibold tracking-[0.05em] uppercase text-[#9AA0A8]">
                    <span>Rayna option</span>
                    <span>Seller</span>
                    <span>Competitor option</span>
                    <span className="text-right">Rayna</span>
                    <span className="text-right">Competitor</span>
                    <span>Gap</span>
                    <span>Mapped</span>
                    <span />
                  </div>
                  <div className="divide-y divide-[#F1F2F4]">
                    {group.items.map((m) => (
                      <div
                        key={m.mapping_id}
                        className="grid grid-cols-[2fr_1.4fr_2fr_0.8fr_0.8fr_0.7fr_0.8fr_60px] gap-3 px-5 py-3.5 hover:bg-[#FAFBFC] transition-colors items-center"
                      >
                        <div className="min-w-0">
                          <div className="text-[13px] text-[#1F2127] line-clamp-2 leading-snug">
                            {m.rayna_option_name}
                          </div>
                          <div className="text-[10.5px] text-[#9AA0A8] font-mono mt-1">
                            {fmtBasis(m.rayna_basis)}
                          </div>
                        </div>
                        <a
                          href={m.listing_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[12.5px] font-mono text-[#3D424B] hover:text-[#0E6F6A] inline-flex items-center gap-1.5 truncate"
                        >
                          {m.seller_domain}
                          <ExternalLink className="w-3 h-3 opacity-50 shrink-0" />
                        </a>
                        <div className="min-w-0">
                          <div className="text-[13px] text-[#1F2127] line-clamp-2 leading-snug">
                            {m.competitor_option_name}
                          </div>
                          <div className="text-[10.5px] text-[#9AA0A8] font-mono mt-1">
                            {fmtBasis(m.competitor_basis)}
                          </div>
                        </div>
                        <div className="text-right whitespace-nowrap">
                          <div className="tnum text-[13px] font-semibold text-[#16181D]">
                            {fmtAED(m.rayna_price, m.rayna_currency)}
                          </div>
                          {m.rayna_date_price_source === "default" && (
                              <div
                                title="No observation for this date; showing default variant price"
                                className="inline-flex items-center gap-1 text-[9.5px] text-[#9A6510] font-semibold mt-0.5"
                              >
                                <AlertTriangle className="w-3 h-3" />
                                default
                              </div>
                            )}
                        </div>
                        <div className="text-right whitespace-nowrap">
                          <div className="tnum text-[13px] font-semibold text-[#16181D]">
                            {fmtAED(m.competitor_price, m.competitor_currency)}
                          </div>
                          {m.competitor_price != null &&
                            (m.competitor_currency || "AED").toUpperCase() !==
                              "AED" && (
                              <div className="tnum text-[10.5px] text-[#9AA0A8]">
                                {fmtMoney(m.competitor_price, m.competitor_currency)}
                              </div>
                            )}
                          {m.competitor_date_price_source === "default" && (
                              <div
                                title="No observation for this date; showing default variant price"
                                className="inline-flex items-center gap-1 text-[9.5px] text-[#9A6510] font-semibold mt-0.5"
                              >
                                <AlertTriangle className="w-3 h-3" />
                                default
                              </div>
                            )}
                        </div>
                        <div className="whitespace-nowrap">
                          {m.rayna_basis === m.competitor_basis ? (
                            priceGap(
                              toAED(m.rayna_price, m.rayna_currency),
                              toAED(m.competitor_price, m.competitor_currency),
                            )
                          ) : (
                            <span className="text-[11px] text-[#9A6510]">
                              basis ⚠
                            </span>
                          )}
                        </div>
                        <span className="tnum text-[11px] text-[#9AA0A8] whitespace-nowrap">
                          {fmtDate(m.created_at)}
                        </span>
                        <div className="flex justify-end">
                          <UnmapButton mappingId={m.mapping_id} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
