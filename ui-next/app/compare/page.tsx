import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ExternalLink, Info, MapPin, ArrowLeftRight } from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import { CompareActionBar } from "@/components/CompareActionBar";
import { PriceGap } from "@/components/PriceGap";
import {
  getMappingWorkspace,
  type CompetitorOptionForMapping,
} from "@/lib/api";
import { fmtBasis, fmtField, fmtMoney } from "@/lib/format";
import { requirePermission } from "@/lib/session";
import {
  FIELDS,
  VENDOR_KEYS,
  hasMeaningfulData,
  pickFirst,
  type FieldRow,
} from "@/lib/fingerprint";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{
  productId?: string;
  raynaOptionId?: string;
  competitorOptionId?: string;
  date?: string;
}>;

function isValidIsoDate(s: string | undefined): s is string {
  return !!s && /^\d{4}-\d{2}-\d{2}$/.test(s);
}

export default async function ComparePage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const user = await requirePermission("mapping.view");
  const sp = await searchParams;
  const productId = sp.productId ? parseInt(sp.productId, 10) : NaN;
  const raynaOptionId = sp.raynaOptionId ? parseInt(sp.raynaOptionId, 10) : NaN;
  const competitorOptionId = sp.competitorOptionId
    ? parseInt(sp.competitorOptionId, 10)
    : NaN;
  const today = new Date().toISOString().slice(0, 10);
  const date = isValidIsoDate(sp.date) ? sp.date : today;

  if (
    !Number.isFinite(productId) ||
    !Number.isFinite(raynaOptionId) ||
    !Number.isFinite(competitorOptionId)
  ) {
    notFound();
  }

  let workspace;
  try {
    workspace = await getMappingWorkspace(productId, date);
  } catch (e) {
    if (String(e).includes("404")) notFound();
    throw e;
  }

  const rayna = workspace.rayna_options.find((o) => o.id === raynaOptionId);
  if (!rayna) notFound();

  let sellerDomain = "";
  let listingUrl = "";
  let competitor: CompetitorOptionForMapping | undefined;
  for (const s of workspace.sellers) {
    const match = s.options.find((o) => o.option_id === competitorOptionId);
    if (match) {
      competitor = match;
      sellerDomain = s.seller_domain;
      listingUrl = match.listing_url;
      break;
    }
  }
  if (!competitor) notFound();

  const raynaFp = rayna.fingerprint as Record<string, unknown>;
  const compFp = competitor.fingerprint as Record<string, unknown>;
  const compThin = !hasMeaningfulData(compFp);

  const dateLabel = new Date(date + "T00:00:00").toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  const isToday = date === today;

  const extraCompKeys = Object.keys(compFp).filter(
    (k) =>
      VENDOR_KEYS.has(k) ||
      !FIELDS.some((f) => f.compKeys.includes(k)) &&
        !["pricing_basis"].includes(k),
  );
  const extraRaynaKeys = Object.keys(raynaFp).filter(
    (k) =>
      VENDOR_KEYS.has(k) ||
      !FIELDS.some((f) => f.raynaKeys.includes(k)) &&
        !["pricing_basis"].includes(k),
  );

  return (
    <AppLayout user={user}
      title="Compare"
      subtitle={`${workspace.product.name} · Rayna vs ${sellerDomain}`}
    >
      <div className="max-w-[1280px] mx-auto px-8 py-6">
        <div className="flex items-center gap-1.5 text-[12.5px] text-[#98A2B3] mb-4">
          <Link
            href={`/?productId=${productId}&raynaOptionId=${raynaOptionId}`}
            className="inline-flex items-center gap-1 hover:text-[#344054]"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            Back to mapping
          </Link>
          <span>·</span>
          <span className="inline-flex items-center gap-1">
            <MapPin className="w-3 h-3" />
            {workspace.product.city}, {workspace.product.country}
          </span>
          <span>·</span>
          <span>
            {dateLabel}
            {isToday && (
              <span className="ml-1 text-[#EA580C] font-semibold">(today)</span>
            )}
          </span>
        </div>

        <div className="flex items-start gap-3.5 mb-6">
          <div className="w-[52px] h-[52px]  bg-[#FFF4ED] border border-[#3D424B] flex items-center justify-center text-[#EA580C]">
            <ArrowLeftRight className="w-6 h-6" />
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-[22px] font-semibold tracking-[-0.02em] mb-1">
              {workspace.product.name}
            </h1>
            <div className="text-[12.5px] text-[#667085]">
              Side-by-side comparison of one Rayna option vs one competitor option
            </div>
          </div>
        </div>

        {compThin && (
          <div className="mb-5  border border-[#EFD8A6] bg-[#FBF1DE] px-4 py-3 flex items-start gap-2.5">
            <Info className="w-4 h-4 text-[#9A6510] mt-0.5 shrink-0" />
            <div className="text-[12.5px] text-[#7A4F08] leading-snug">
              <span className="font-semibold">Limited competitor data.</span>{" "}
              This seller&rsquo;s feed exposes variant name + price only. Full
              descriptions, inclusions, and cancellation policy live on the
              seller&rsquo;s PDP.
              {listingUrl && (
                <>
                  {" "}
                  <a
                    href={listingUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline font-semibold hover:text-[#5A3806]"
                  >
                    Open on {sellerDomain} ↗
                  </a>
                </>
              )}
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-4 mb-5">
          <SideHeader
            side="Rayna"
            name={rayna.name}
            price={rayna.price}
            currency={rayna.currency}
            basis={rayna.pricing_basis}
            accent="teal"
          />
          <SideHeader
            side={sellerDomain}
            name={competitor.name}
            price={competitor.price}
            currency={competitor.currency}
            basis={competitor.pricing_basis}
            accent="neutral"
            externalUrl={listingUrl}
          />
        </div>

        <div className="mb-5  border border-[#E4E7EC] bg-white px-5 py-4">
          <PriceGap
            raynaPrice={rayna.price}
            raynaCurrency={rayna.currency}
            compPrice={competitor.price}
            compCurrency={competitor.currency}
          />
        </div>

        <div className="mb-5">
          <CompareActionBar
            productId={productId}
            raynaOptionId={raynaOptionId}
            raynaOptionName={rayna.name}
            competitorOptionId={competitorOptionId}
            existingMapping={competitor.mapping}
          />
        </div>

        <FieldsTable
          rows={FIELDS}
          raynaFp={raynaFp}
          compFp={compFp}
          sellerDomain={sellerDomain}
        />

        <VendorPanel
          raynaFp={raynaFp}
          compFp={compFp}
          extraRaynaKeys={extraRaynaKeys}
          extraCompKeys={extraCompKeys}
          sellerDomain={sellerDomain}
        />
      </div>
    </AppLayout>
  );
}

function SideHeader({
  side,
  name,
  price,
  currency,
  basis,
  accent,
  externalUrl,
}: {
  side: string;
  name: string;
  price: number | null;
  currency: string | null;
  basis: string;
  accent: "teal" | "neutral";
  externalUrl?: string;
}) {
  const isTeal = accent === "teal";
  return (
    <div
      className={` border px-5 py-4 ${
        isTeal
          ? "bg-[#FFF4ED] border-[#F59E0B]"
          : "bg-white border-[#E4E7EC]"
      }`}
    >
      <div
        className={`text-[10.5px] font-semibold uppercase tracking-[0.09em] mb-1.5 ${
          isTeal ? "text-[#EA580C]" : "text-[#475467]"
        }`}
      >
        {isTeal ? "Rayna" : side}
      </div>
      {externalUrl ? (
        <a
          href={externalUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[15px] font-semibold text-[#101828] hover:text-[#EA580C] inline-flex items-start gap-1.5 leading-snug mb-2"
        >
          <span>{name}</span>
          <ExternalLink className="w-3.5 h-3.5 opacity-50 mt-1 shrink-0" />
        </a>
      ) : (
        <div className="text-[15px] font-semibold text-[#101828] leading-snug mb-2">
          {name}
        </div>
      )}
      <div className="flex items-baseline gap-2">
        <span className="tnum text-[20px] font-semibold text-[#101828]">
          {fmtMoney(price, currency)}
        </span>
        <span className="text-[11px] font-mono text-[#667085]">
          {fmtBasis(basis)}
        </span>
      </div>
    </div>
  );
}

function FieldsTable({
  rows,
  raynaFp,
  compFp,
  sellerDomain,
}: {
  rows: FieldRow[];
  raynaFp: Record<string, unknown>;
  compFp: Record<string, unknown>;
  sellerDomain: string;
}) {
  return (
    <div className=" border border-[#E4E7EC] bg-white overflow-hidden mb-5">
      <div className="grid grid-cols-[1fr_1.5fr_1.5fr] gap-3 px-5 py-3 bg-[#F9FAFB] border-b border-[#E4E7EC] text-[10.5px] font-semibold uppercase tracking-[0.05em] text-[#98A2B3]">
        <span>Field</span>
        <span>Rayna</span>
        <span>{sellerDomain}</span>
      </div>
      <div className="divide-y divide-[#F1F2F4]">
        {rows.map((row) => (
          <FieldRowView
            key={row.label}
            row={row}
            raynaFp={raynaFp}
            compFp={compFp}
          />
        ))}
      </div>
    </div>
  );
}

function FieldRowView({
  row,
  raynaFp,
  compFp,
}: {
  row: FieldRow;
  raynaFp: Record<string, unknown>;
  compFp: Record<string, unknown>;
}) {
  const rRaw = pickFirst(raynaFp, row.raynaKeys);
  const cRaw = pickFirst(compFp, row.compKeys);
  const rFormatted = row.format && rRaw != null ? row.format(rRaw) : rRaw;
  const cFormatted = row.format && cRaw != null ? row.format(cRaw) : cRaw;
  const r = fmtField(rFormatted);
  const c = fmtField(cRaw != null ? cFormatted : cRaw);

  const bothPresent = !r.missing && !c.missing;
  const differs = bothPresent && r.text !== c.text;
  const bothMissing = r.missing && c.missing;

  return (
    <div
      className={`grid grid-cols-[1fr_1.5fr_1.5fr] gap-3 px-5 py-3 items-start text-[13px] ${
        differs ? "bg-[#FBF1DE]/40" : ""
      } ${bothMissing ? "opacity-60" : ""}`}
    >
      <span className="text-[#667085] font-medium">{row.label}</span>
      <ValueCell v={r} isList={Array.isArray(rRaw)} />
      <ValueCell v={c} isList={Array.isArray(cRaw)} highlight={differs} />
    </div>
  );
}

function ValueCell({
  v,
  isList,
  highlight,
}: {
  v: { text: string; missing: boolean };
  isList: boolean;
  highlight?: boolean;
}) {
  if (v.missing) {
    return (
      <span className="text-[#D0D5DD] italic text-[12px]">{v.text}</span>
    );
  }
  if (isList) {
    const items = v.text.split(", ");
    return (
      <ul
        className={`list-disc list-inside space-y-0.5 leading-snug ${
          highlight ? "text-[#101828] font-medium" : "text-[#344054]"
        }`}
      >
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    );
  }
  return (
    <span
      className={`leading-snug ${
        highlight ? "text-[#101828] font-semibold" : "text-[#344054]"
      }`}
    >
      {v.text}
    </span>
  );
}

function VendorPanel({
  raynaFp,
  compFp,
  extraRaynaKeys,
  extraCompKeys,
  sellerDomain,
}: {
  raynaFp: Record<string, unknown>;
  compFp: Record<string, unknown>;
  extraRaynaKeys: string[];
  extraCompKeys: string[];
  sellerDomain: string;
}) {
  if (extraRaynaKeys.length === 0 && extraCompKeys.length === 0) return null;
  return (
    <details className=" border border-[#E4E7EC] bg-white overflow-hidden">
      <summary className="cursor-pointer px-5 py-3 text-[11px] font-semibold uppercase tracking-[0.05em] text-[#98A2B3] hover:bg-[#F9FAFB]">
        Vendor-specific fields
      </summary>
      <div className="grid grid-cols-2 gap-0 border-t border-[#E4E7EC]">
        <KVList
          title="Rayna"
          fp={raynaFp}
          keys={extraRaynaKeys}
          borderRight
        />
        <KVList title={sellerDomain} fp={compFp} keys={extraCompKeys} />
      </div>
    </details>
  );
}

function KVList({
  title,
  fp,
  keys,
  borderRight,
}: {
  title: string;
  fp: Record<string, unknown>;
  keys: string[];
  borderRight?: boolean;
}) {
  return (
    <div className={`px-5 py-3 ${borderRight ? "border-r border-[#F2F4F7]" : ""}`}>
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-[#667085] mb-2">
        {title}
      </div>
      {keys.length === 0 ? (
        <div className="text-[12px] text-[#D0D5DD] italic">—</div>
      ) : (
        <ul className="text-[12px] font-mono text-[#344054] space-y-1">
          {keys.map((k) => (
            <li key={k}>
              <span className="text-[#98A2B3]">{k}:</span>{" "}
              {String(fp[k] ?? "—")}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

