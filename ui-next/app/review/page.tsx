import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import { VerdictBadge } from "@/components/VerdictBadge";
import { getReviewQueue } from "@/lib/api";
import { fmtMoney, fmtBasis, fmtAED } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ReviewPage() {
  const queue = await getReviewQueue();

  return (
    <AppLayout
      title="Mapping review"
      subtitle="Confirm or correct AI-proposed competitor matches"
    >
      <div className="max-w-[1480px] mx-auto px-8 py-7">
        <div className="mb-6 flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-[22px] font-semibold tracking-[-0.02em]">
              Review queue
            </h1>
            <p className="text-[13.5px] text-[#8A8F98] mt-1">
              <span className="tnum text-[#3D424B] font-semibold">{queue.length}</span>{" "}
              items flagged — low confidence (&lt;0.70) or pricing-basis mismatch.
              High-confidence matches were auto-approved.
            </p>
          </div>
        </div>

        {queue.length === 0 ? (
          <div className="bg-white border border-dashed border-[#D5D7DC] rounded-[14px] px-8 py-16 text-center text-[#8A8F98] text-[13px]">
            Empty queue. Either we're doing great, or no Claude mapping has run.
          </div>
        ) : (
          <div className="bg-white border border-[#EBECEF] rounded-[13px] overflow-hidden">
            <div className="grid grid-cols-[1.4fr_1.8fr_1.3fr_1.8fr_1fr_0.8fr_0.8fr_2fr] gap-3 px-5 py-[11px] bg-[#FAFBFC] border-b border-[#EBECEF] text-[11px] font-semibold tracking-[0.04em] uppercase text-[#9AA0A8]">
              <span>Product</span>
              <span>Rayna option</span>
              <span>Seller</span>
              <span>Competitor option</span>
              <span>Verdict</span>
              <span className="text-right">Rayna</span>
              <span className="text-right">Competitor</span>
              <span>Why review</span>
            </div>
            <div className="divide-y divide-[#F1F2F4]">
              {queue.map((item) => {
                const basisMismatch =
                  item.rayna_basis !== item.competitor_basis &&
                  item.rayna_basis !== "unknown" &&
                  item.competitor_basis !== "unknown";
                const reasons: string[] = [];
                if (item.confidence < 0.7)
                  reasons.push(`conf ${item.confidence.toFixed(2)}`);
                if (basisMismatch)
                  reasons.push(
                    `basis: ${fmtBasis(item.rayna_basis)} vs ${fmtBasis(item.competitor_basis)}`,
                  );

                return (
                  <div
                    key={item.mapping_id}
                    className="grid grid-cols-[1.4fr_1.8fr_1.3fr_1.8fr_1fr_0.8fr_0.8fr_2fr] gap-3 px-5 py-3.5 items-center hover:bg-[#FAFBFC] transition-colors"
                  >
                    <Link
                      href={`/comparison/product/${item.product_id}`}
                      className="text-[12.5px] font-semibold text-[#EA580C] hover:text-[#C2410C]"
                    >
                      {item.product_name}
                    </Link>
                    <div className="min-w-0">
                      <div className="text-[12.5px] text-[#1F2127] line-clamp-2 leading-snug">
                        {item.rayna_option_name}
                      </div>
                      <div className="text-[10.5px] font-mono text-[#9AA0A8] mt-1">
                        {fmtBasis(item.rayna_basis)}
                      </div>
                    </div>
                    <span className="text-[12.5px] font-mono text-[#3D424B] truncate">
                      {item.seller_domain}
                    </span>
                    <div className="min-w-0">
                      <div className="text-[12.5px] text-[#1F2127] line-clamp-2 leading-snug">
                        {item.competitor_option_name}
                      </div>
                      <div className="text-[10.5px] font-mono text-[#9AA0A8] mt-1">
                        {fmtBasis(item.competitor_basis)}
                      </div>
                    </div>
                    <VerdictBadge
                      verdict={item.verdict}
                      confidence={item.confidence}
                    />
                    <span className="tnum text-right text-[12.5px] font-semibold text-[#16181D] whitespace-nowrap">
                      {fmtMoney(item.rayna_price, item.rayna_currency)}
                    </span>
                    <div className="text-right whitespace-nowrap">
                      <div className="tnum text-[12.5px] font-semibold text-[#16181D]">
                        {fmtAED(item.competitor_price, item.competitor_currency)}
                      </div>
                      {item.competitor_price != null &&
                        (item.competitor_currency || "AED").toUpperCase() !==
                          "AED" && (
                          <div className="tnum text-[10px] text-[#9AA0A8]">
                            {fmtMoney(item.competitor_price, item.competitor_currency)}
                          </div>
                        )}
                    </div>
                    <div className="text-[11.5px] text-[#5C6069] min-w-0">
                      <div className="flex flex-wrap gap-1 mb-1">
                        {reasons.map((r) => (
                          <span
                            key={r}
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-[5px] bg-[#FBF1DE] text-[#9A6510] text-[10px] font-semibold border border-[#EFD8A6]"
                          >
                            <AlertTriangle className="w-3 h-3" />
                            {r}
                          </span>
                        ))}
                      </div>
                      <div className="italic text-[#9AA0A8] leading-snug line-clamp-2">
                        {item.diff_notes}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </AppLayout>
  );
}
