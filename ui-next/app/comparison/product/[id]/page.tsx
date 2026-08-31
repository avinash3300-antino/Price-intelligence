import Link from "next/link";
import { ArrowLeft, ExternalLink, MapPin } from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import { CompetitorCard } from "@/components/CompetitorCard";
import {
  getProductComparison,
  type RaynaOptionWithMappings,
} from "@/lib/api";
import { fmtMoney, fmtBasis, fmtPercent, fmtAED } from "@/lib/format";
import { notFound } from "next/navigation";
import { requirePermission } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function ProductPage(props: {
  params: Promise<{ id: string }>;
}) {
  const user = await requirePermission("comparison.view");
  const { id } = await props.params;
  const productId = parseInt(id, 10);

  let data;
  try {
    data = await getProductComparison(productId);
  } catch (e) {
    if (String(e).includes("404")) notFound();
    throw e;
  }

  const { product, options } = data;

  return (
    <AppLayout user={user}
      title={product.name}
      subtitle="Option-level comparison against the market"
    >
      <div className="max-w-[1280px] mx-auto px-8 py-6">
        <div className="flex items-center gap-1.5 text-[12.5px] text-[#98A2B3] mb-4">
          <Link href="/comparison" className="hover:text-[#344054]">
            Portfolio
          </Link>
          <span>/</span>
          <span className="text-[#344054] font-medium">{product.name}</span>
        </div>

        <div className="flex items-start gap-3.5 mb-6">
          <div className="w-[52px] h-[52px]  bg-[#FFF4ED] border border-[#3D424B] flex items-center justify-center text-2xl">
            🌆
          </div>
          <div className="flex-1">
            <h1 className="text-[22px] font-semibold tracking-[-0.02em] mb-1">
              {product.name}
            </h1>
            <div className="flex items-center gap-3.5 text-[12.5px] text-[#667085]">
              <span className="inline-flex items-center gap-1">
                <MapPin className="w-3.5 h-3.5" />
                {product.city}, {product.country}
              </span>
              <span className="text-[#D5D7DC]">·</span>
              <span>{options.length} bookable options</span>
            </div>
          </div>
          <div className="flex items-center gap-1.5 text-[12px] text-[#98A2B3] bg-[#F2F4F7] border border-[#E7E8EB]  px-[11px] py-1.5">
            <span>🇦🇪</span> {product.currency} · {product.market}
          </div>
        </div>

        {options.length === 0 ? (
          <div className="bg-white border border-dashed border-[#D5D7DC]  px-8 py-16 text-center text-[#667085] text-[13px]">
            No Rayna options extracted for this product.
          </div>
        ) : (
          <div className="space-y-9">
            {options.map((bundle) => (
              <OptionSection key={bundle.option.id} bundle={bundle} />
            ))}
          </div>
        )}
      </div>
    </AppLayout>
  );
}

function OptionSection({ bundle }: { bundle: RaynaOptionWithMappings }) {
  const { option, mappings } = bundle;

  const comparable = mappings.filter(
    (m) =>
      m.verdict !== "different" &&
      m.price != null &&
      m.price > 0 &&
      m.pricing_basis === option.pricing_basis &&
      m.currency === option.currency,
  );

  let headline: React.ReactNode = null;
  if (option.price != null && comparable.length > 0) {
    const cheapest = comparable.reduce((a, b) =>
      (a.price ?? Infinity) < (b.price ?? Infinity) ? a : b,
    );
    const cPrice = cheapest.price!;
    const diff = cPrice - option.price;
    const pct = (diff / option.price) * 100;
    if (diff < -0.5) {
      headline = (
        <Headline
          tone="bad"
          headline={`We are ${fmtPercent(Math.abs(pct))} higher than the cheapest competitor.`}
          detail={`${cheapest.seller_domain} sells at ${fmtAED(cPrice, cheapest.currency)} — we list ${fmtMoney(option.price, option.currency)}.`}
        />
      );
    } else if (diff > 0.5) {
      headline = (
        <Headline
          tone="good"
          headline="We are cheapest like-for-like."
          detail={`Next cheapest is ${cheapest.seller_domain} at ${fmtAED(cPrice, cheapest.currency)} (${fmtPercent(pct, { sign: true })}).`}
        />
      );
    } else {
      headline = (
        <Headline
          tone="neutral"
          headline="Matched at market."
          detail={`${cheapest.seller_domain} lists at the same ${fmtAED(cPrice, cheapest.currency)}.`}
        />
      );
    }
  } else if (mappings.length > 0) {
    headline = (
      <Headline
        tone="warn"
        headline="No like-for-like comparison available."
        detail="Mappings exist but all suffer from pricing-basis or currency mismatch, or competitors didn't list a price."
      />
    );
  }

  const ncomp = mappings.filter((m) => m.verdict !== "different").length;
  const ndiff = mappings.length - ncomp;

  return (
    <section>
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <div>
          <h2 className="text-[16px] font-semibold text-[#101828] -tracking-[0.01em]">
            {option.name}
          </h2>
          <div className="text-[12.5px] text-[#667085] mt-1">
            <span className="tnum font-semibold text-[#344054]">
              {fmtMoney(option.price, option.currency)}
            </span>
            <span className="mx-2 text-[#D5D7DC]">·</span>
            <span className="font-mono">{fmtBasis(option.pricing_basis)}</span>
            <span className="mx-2 text-[#D5D7DC]">·</span>
            <span>
              {ncomp} comparable {ncomp === 1 ? "match" : "matches"}
            </span>
            {ndiff > 0 && (
              <>
                <span className="mx-2 text-[#D5D7DC]">·</span>
                <span className="text-[#A5AAB2]">
                  {ndiff} judged different (hidden)
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      {headline && <div className="mb-4">{headline}</div>}

      {ncomp === 0 && ndiff === 0 && (
        <div className="bg-white border border-dashed border-[#D5D7DC]  px-6 py-8 text-center text-[12.5px] text-[#667085]">
          No competitor mappings yet.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {mappings
          .filter((m) => m.verdict !== "different")
          .map((m) => (
            <CompetitorCard
              key={m.mapping_id}
              rayna={{
                name: option.name,
                price: option.price,
                currency: option.currency,
                basis: option.pricing_basis,
                fingerprint: option.fingerprint,
              }}
              competitor={{
                domain: m.seller_domain,
                name: m.name,
                price: m.price,
                currency: m.currency,
                basis: m.pricing_basis,
                fingerprint: m.fingerprint,
                listingUrl: m.listing_url,
              }}
              verdict={m.verdict}
              confidence={m.confidence}
              diffNotes={m.diff_notes}
            />
          ))}
      </div>
    </section>
  );
}

function Headline({
  tone,
  headline,
  detail,
}: {
  tone: "good" | "bad" | "warn" | "neutral";
  headline: string;
  detail: string;
}) {
  const styles = {
    good: { bg: "#FFF4ED", border: "#FDBA74", text: "#C2410C", sub: "#2F6E68" },
    bad: { bg: "#FBEAE8", border: "#F1C7C2", text: "#B5342C", sub: "#9A4138" },
    warn: { bg: "#FBF1DE", border: "#EFD8A6", text: "#9A6510", sub: "#A07A33" },
    neutral: { bg: "#FAFBFC", border: "#EBECEF", text: "#3D424B", sub: "#5C6069" },
  } as const;
  const s = styles[tone];
  return (
    <div
      className=" border px-[18px] py-[14px]"
      style={{ background: s.bg, borderColor: s.border }}
    >
      <div className="text-[13.5px] font-semibold" style={{ color: s.text }}>
        {headline}
      </div>
      <div className="text-[12.5px] mt-1 leading-snug" style={{ color: s.sub }}>
        {detail}
      </div>
    </div>
  );
}
