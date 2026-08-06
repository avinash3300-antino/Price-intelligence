import Link from "next/link";
import { AppLayout } from "@/components/AppLayout";
import { getMapped } from "@/lib/api";
import { MappedDatePill } from "@/components/MappedDatePill";
import { MappedFilters } from "@/components/MappedFilters";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{ date?: string }>;

function isValidIsoDate(s: string | undefined): s is string {
  return !!s && /^\d{4}-\d{2}-\d{2}$/.test(s);
}

export default async function MappedPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const sp = await searchParams;
  // Default to tomorrow so same-day OTA cutoffs don't skew the gap — matches
  // the Mapping tab default.
  const tomorrow = (() => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    return d.toISOString().slice(0, 10);
  })();
  const date = isValidIsoDate(sp.date) ? sp.date : tomorrow;
  const items = await getMapped(date);

  const dateLabel = new Date(date + "T00:00:00").toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });

  return (
    <AppLayout>
      <div className="max-w-[1480px] mx-auto px-8 py-7 w-full">
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
            <MappedFilters items={items} />

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
