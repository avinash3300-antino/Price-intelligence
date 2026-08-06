import Link from "next/link";
import { Layers, Trophy, Flag, ArrowRight, Store } from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import { ComparisonProductsTable } from "@/components/ComparisonProductsTable";
import { getDashboard, type PipelineStats, type DashboardStat } from "@/lib/api";

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
          <ComparisonProductsTable stats={stats} />
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

