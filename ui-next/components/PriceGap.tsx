import { fmtMoney, fmtPercent, toAED } from "@/lib/format";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";

export function PriceGap({
  raynaPrice,
  raynaCurrency,
  compPrice,
  compCurrency,
}: {
  raynaPrice: number | null;
  raynaCurrency: string | null;
  compPrice: number | null;
  compCurrency: string | null;
}) {
  if (raynaPrice == null || compPrice == null) {
    return <span className="text-[11px] text-[#9AA0A8]">price not stated</span>;
  }

  // Always normalise both sides to AED before computing % gap, so a USD
  // competitor and an AED Rayna option remain directly comparable.
  const raynaAED = toAED(raynaPrice, raynaCurrency) ?? raynaPrice;
  const compAED = toAED(compPrice, compCurrency) ?? compPrice;

  const diff = compAED - raynaAED;
  const pct = (diff / raynaAED) * 100;
  const we_cheaper = diff > 0;
  const same = Math.abs(diff) < 0.5;

  let color: string;
  let bg: string;
  let Arrow: typeof ArrowDown;
  let signLabel: string;
  if (same) {
    color = "#5C6069";
    bg = "#FAFBFC";
    Arrow = Minus;
    signLabel = "match";
  } else if (we_cheaper) {
    color = "#C2410C";
    bg = "#FFF7ED";
    Arrow = ArrowUp;
    signLabel = "we win";
  } else {
    color = "#B5342C";
    bg = "#FBEAE8";
    Arrow = ArrowDown;
    signLabel = "we lose";
  }

  const compForeign =
    compCurrency != null && compCurrency.toUpperCase() !== "AED";

  return (
    <div className="flex items-baseline gap-3 text-[13px] flex-wrap">
      <span className="text-[#3D424B]">
        <span className="text-[10.5px] text-[#9AA0A8]">Rayna</span>{" "}
        <span className="tnum font-semibold">{fmtMoney(raynaAED, "AED")}</span>
      </span>
      <span className="text-[#D5D7DC]">·</span>
      <span className="text-[#3D424B]">
        <span className="text-[10.5px] text-[#9AA0A8]">Comp</span>{" "}
        <span className="tnum font-semibold">{fmtMoney(compAED, "AED")}</span>
        {compForeign && (
          <span className="ml-1.5 text-[10.5px] text-[#9AA0A8] tnum">
            ({fmtMoney(compPrice, compCurrency)})
          </span>
        )}
      </span>
      <span
        className="inline-flex items-center gap-1 font-semibold px-2 py-0.5 rounded-[6px] text-[11.5px]"
        style={{ color, background: bg }}
      >
        <Arrow className="w-3 h-3" strokeWidth={3} />
        <span className="tnum">{fmtPercent(pct, { sign: true })}</span>
        <span className="text-[10.5px] font-normal opacity-80">· {signLabel}</span>
      </span>
    </div>
  );
}
