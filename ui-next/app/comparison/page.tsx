import Link from "next/link";
import { Layers, Trophy, Flag, ArrowRight, Store, CheckCircle2 } from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import { getDashboard, type PipelineStats, type DashboardStat } from "@/lib/api";
import { fmtMoney, fmtPercent, fmtAED } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ComparisonPage() {
  const { products: stats, pipeline } = await getDashboard();

  return (
    <AppLayout
      title="Portfolio overview"
      subtitle="Where we stand on price across the catalogue"
    >
      <div className="max-w-[1280px] mx-auto px-8 pt-7 pb-16">
        <KPIRow pipeline={pipeline} stats={stats} />

        {pipeline.needs_review > 0 && (
          <Link
            href="/review"
            className="mt-[22px] w-full flex items-center gap-3.5 bg-gradient-to-r from-[#FFF9EC] to-[#FFFDF8] border border-[#F1DFB4]  px-[18px] py-[15px] hover:border-[#E6CB87] hover:shadow-[0_2px_10px_rgba(193,150,42,0.1)] transition-all"
          >
            <span className="w-[38px] h-[38px] shrink-0  bg-[#F6E2AE] text-[#8A5B0A] flex items-center justify-center">
              <Flag className="w-[18px] h-[18px]" strokeWidth={2} />
            </span>
            <div className="flex-1 text-left">
              <div className="text-[14px] font-semibold text-[#7A4F08]">
                <span className="tnum">{pipeline.needs_review}</span> mappings need
                review
              </div>
              <div className="text-[12.5px] text-[#A07A33] mt-0.5">
                Low-confidence or bundle-mismatch matches Claude couldn't confirm.
                High-confidence matches were auto-approved.
              </div>
            </div>
            <span className="flex items-center gap-1.5 text-[13px] font-semibold text-[#8A5B0A]">
              Open review queue
              <ArrowRight className="w-[15px] h-[15px]" strokeWidth={2.2} />
            </span>
          </Link>
        )}

        <div className="mt-7">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-baseline gap-2.5">
              <h2 className="text-[16px] font-semibold -tracking-[0.01em]">
                Tracked products
              </h2>
              <span className="tnum text-[12.5px] text-[#98A2B3]">
                {pipeline.products} in UAE · Activities
              </span>
            </div>
          </div>

          <div className="bg-white border border-[#E4E7EC]  overflow-hidden">
            <div className="grid grid-cols-[2.4fr_0.8fr_1fr_1.4fr_0.9fr] gap-3 px-5 py-[11px] bg-[#F9FAFB] border-b border-[#E4E7EC] text-[11px] font-semibold tracking-[0.04em] uppercase text-[#98A2B3]">
              <span>Product</span>
              <span className="text-center">Options</span>
              <span className="text-center">Sellers</span>
              <span>Price position</span>
              <span className="text-right">Refreshed</span>
            </div>
            {stats.map((s) => (
              <ProductRow key={s.product.id} stat={s} />
            ))}
          </div>
        </div>
      </div>
    </AppLayout>
  );
}

function KPIRow({
  pipeline,
  stats,
}: {
  pipeline: PipelineStats;
  stats: DashboardStat[];
}) {
  // derive: how many products are price-leaders (we are cheapest)
  let leaders = 0;
  let higher = 0;
  for (const s of stats) {
    const c = s.cheapest_competitor;
    if (!c) continue;
    if (c.gap_pct > 1) leaders += 1;
    else if (c.gap_pct < -1) higher += 1;
  }
  const leadersPct = stats.length
    ? Math.round((leaders / stats.length) * 100)
    : 0;

  return (
    <div className="grid grid-cols-4 gap-4">
      <KPICard
        label="Products tracked"
        value={pipeline.products}
        sub={`${pipeline.rayna_options} bookable options`}
        icon={<Layers className="w-[15px] h-[15px]" />}
        iconBg="bg-[#EAF0FA]"
        iconColor="text-[#3A6DB5]"
      />
      <KPICard
        label="We are price leader"
        value={`${leadersPct}%`}
        sub={`${leaders} of ${stats.length} products`}
        icon={<Trophy className="w-[15px] h-[15px]" />}
        iconBg="bg-[#FFF4ED]"
        iconColor="text-[#C2410C]"
        valueTone="text-[#101828]"
      />
      <KPICard
        label="Need review"
        value={pipeline.needs_review}
        sub="low-confidence matches"
        icon={<Flag className="w-[15px] h-[15px]" />}
        iconBg="bg-[#FBF1DE]"
        iconColor="text-[#9A6510]"
      />
      <KPICard
        label="Sellers discovered"
        value={pipeline.competitors}
        sub={`${pipeline.scraped_listings} PDPs scraped`}
        icon={<Store className="w-[15px] h-[15px]" />}
        iconBg="bg-[#FFF4ED]"
        iconColor="text-[#EA580C]"
      />
    </div>
  );
}

function KPICard({
  label,
  value,
  sub,
  icon,
  iconBg,
  iconColor,
  valueTone = "text-[#101828]",
}: {
  label: string;
  value: string | number;
  sub: string;
  icon: React.ReactNode;
  iconBg: string;
  iconColor: string;
  valueTone?: string;
}) {
  return (
    <div className="bg-white border border-[#E4E7EC]  px-[18px] py-4">
      <div className="flex items-center gap-2 mb-[13px]">
        <span
          className={`w-[26px] h-[26px]  inline-flex items-center justify-center ${iconBg} ${iconColor}`}
        >
          {icon}
        </span>
        <span className="text-[12px] text-[#7A7F88] font-medium">{label}</span>
      </div>
      <div
        className={`tnum text-[28px] font-semibold tracking-[-0.02em] ${valueTone}`}
      >
        {value}
      </div>
      <div className="text-[11.5px] text-[#98A2B3] mt-1">{sub}</div>
    </div>
  );
}

function ProductRow({ stat }: { stat: DashboardStat }) {
  const { product, option_count, seller_count, cheapest_competitor } = stat;

  let position: { label: string; color: string; bg: string; border: string } = {
    label: "No match yet",
    color: "#7A7F88",
    bg: "#F2F3F5",
    border: "#E2E3E7",
  };
  if (cheapest_competitor) {
    const pct = cheapest_competitor.gap_pct;
    if (pct > 1) {
      position = {
        label: `Cheapest · ${fmtPercent(Math.abs(pct))} under`,
        color: "#C2410C",
        bg: "#FFF4ED",
        border: "#FDBA74",
      };
    } else if (pct < -1) {
      position = {
        label: `${fmtPercent(Math.abs(pct))} over market`,
        color: "#B5342C",
        bg: "#FBEAE8",
        border: "#F1C7C2",
      };
    } else {
      position = {
        label: "Matched at market",
        color: "#9A6510",
        bg: "#FBF1DE",
        border: "#EFD8A6",
      };
    }
  }

  return (
    <Link
      href={`/comparison/product/${product.id}`}
      className="grid grid-cols-[2.4fr_0.8fr_1fr_1.4fr_0.9fr] gap-3 items-center px-5 py-[14px] border-b border-[#F2F4F7] last:border-b-0 hover:bg-[#F9FAFB] transition-colors"
    >
      <div className="flex items-center gap-[11px] min-w-0">
        <span className="w-[34px] h-[34px] shrink-0  bg-[#FFF4ED] border border-[#3D424B] grid place-items-center text-[16px]">
          {emojiFor(product.name)}
        </span>
        <div className="min-w-0">
          <div className="text-[13.5px] font-semibold text-[#101828] truncate">
            {product.name}
          </div>
          <div className="text-[11.5px] text-[#98A2B3]">
            Activities · {product.city}
          </div>
        </div>
      </div>
      <span className="tnum text-center text-[13px] font-medium text-[#475467]">
        {option_count}
      </span>
      <span className="tnum text-center text-[13px] font-medium text-[#475467]">
        {seller_count}
      </span>
      <div>
        <span
          className="inline-flex items-center gap-1.5 px-2.5 py-[3px]  text-[11.5px] font-semibold border"
          style={{
            background: position.bg,
            color: position.color,
            borderColor: position.border,
          }}
        >
          <span
            className="w-[6px] h-[6px] rounded-full"
            style={{ background: position.color }}
          />
          {position.label}
        </span>
      </div>
      <span className="tnum text-right text-[11.5px] text-[#98A2B3]">
        {cheapest_competitor
          ? `${fmtAED(cheapest_competitor.price, cheapest_competitor.currency)} on ${cheapest_competitor.domain}`
          : "—"}
      </span>
    </Link>
  );
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
