"use client";

import { useState } from "react";
import { ChevronDown, ExternalLink, AlertTriangle } from "lucide-react";
import { FingerprintDiff } from "@/components/FingerprintDiff";
import { PriceGap } from "@/components/PriceGap";
import { VerdictBadge } from "@/components/VerdictBadge";
import { fmtMoney, fmtBasis, fmtAED } from "@/lib/format";

interface Props {
  rayna: {
    name: string;
    price: number | null;
    currency: string | null;
    basis: string;
    fingerprint: Record<string, unknown>;
  };
  competitor: {
    domain: string;
    name: string;
    price: number | null;
    currency: string | null;
    basis: string;
    fingerprint: Record<string, unknown>;
    listingUrl: string;
  };
  verdict: "identical" | "near" | "different";
  confidence: number;
  diffNotes: string;
}

export function CompetitorCard({
  rayna,
  competitor,
  verdict,
  confidence,
  diffNotes,
}: Props) {
  const [open, setOpen] = useState(false);
  const basisMismatch =
    rayna.basis !== competitor.basis &&
    rayna.basis !== "unknown" &&
    competitor.basis !== "unknown";

  return (
    <div className=" border border-[#E4E7EC] bg-white hover:shadow-sm transition-shadow">
      <div className="p-4">
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <a
                href={competitor.listingUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[13px] font-mono font-semibold text-[#101828] hover:text-[#EA580C] inline-flex items-center gap-1"
              >
                {competitor.domain}
                <ExternalLink className="w-3 h-3 opacity-50" />
              </a>
              <VerdictBadge verdict={verdict} confidence={confidence} />
              {basisMismatch && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5  text-[10.5px] font-semibold bg-[#FBF1DE] text-[#9A6510] border border-[#EFD8A6]">
                  <AlertTriangle className="w-3 h-3" />
                  basis mismatch
                </span>
              )}
            </div>
            <div className="text-[13px] text-[#344054] line-clamp-2 leading-snug">
              {competitor.name}
            </div>
            <div className="text-[11px] text-[#98A2B3] mt-1 font-mono">
              {fmtBasis(competitor.basis)} ·{" "}
              <span className="text-[#344054] font-semibold">
                {fmtAED(competitor.price, competitor.currency)}
              </span>
              {competitor.price != null &&
                (competitor.currency || "AED").toUpperCase() !== "AED" && (
                  <span className="ml-1 text-[#D0D5DD]">
                    ({fmtMoney(competitor.price, competitor.currency)})
                  </span>
                )}
            </div>
          </div>
        </div>

        <div className="mt-3">
          <PriceGap
            raynaPrice={rayna.price}
            raynaCurrency={rayna.currency}
            compPrice={competitor.price}
            compCurrency={competitor.currency}
          />
        </div>

        {diffNotes && (
          <div className="mt-3 text-[12.5px] text-[#475467] italic border-l-2 border-[#E4E7EC] pl-3 leading-snug">
            {diffNotes}
          </div>
        )}

        <button
          onClick={() => setOpen(!open)}
          className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-semibold text-[#EA580C] hover:text-[#C2410C]"
        >
          <ChevronDown
            className={`w-3.5 h-3.5 transition-transform ${open ? "rotate-180" : ""}`}
          />
          {open ? "Hide" : "Show"} fingerprint diff
        </button>

        {open && (
          <div className="mt-3">
            <FingerprintDiff
              rayna={rayna.fingerprint}
              competitor={competitor.fingerprint}
            />
          </div>
        )}
      </div>
    </div>
  );
}
