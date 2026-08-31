"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, ExternalLink, Info, ShieldCheck, UserCheck, X } from "lucide-react";
import { diffRows, venueLooksUnrelated } from "@/lib/fingerprint";
import { fmtAED, fmtBasis, fmtMoney, toAED } from "@/lib/format";
import type { MappedItem } from "@/lib/api";

/** Days after which a captured competitor price stops being trustworthy. */
const STALE_WARN_DAYS = 7;
const STALE_BAD_DAYS = 14;

function daysSince(iso: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return null;
  return Math.floor((Date.now() - t) / 86_400_000);
}

function fmtWhen(iso: string | null): string {
  if (!iso) return "unknown";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "unknown";
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/**
 * The adjudicator's `diff_notes` are prefixed with "[Manual URL paste] " by the
 * from-url endpoint. That's provenance, not part of the finding — it's shown
 * separately in the source row, so strip it from the sentence itself.
 */
function cleanNotes(notes: string): string {
  return notes.replace(/^\[Manual URL paste\]\s*/i, "").trim();
}

export function MappingEvidenceDrawer({
  item,
  onClose,
}: {
  item: MappedItem | null;
  onClose: () => void;
}) {
  const [mounted, setMounted] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => setMounted(true), []);

  // Reset the expand toggle whenever a different mapping is opened, so the
  // drawer always opens on the short "what differs" view.
  useEffect(() => setShowAll(false), [item?.mapping_id]);

  useEffect(() => {
    if (!item) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [item, onClose]);

  const rows = useMemo(
    () =>
      item ? diffRows(item.rayna_fingerprint, item.competitor_fingerprint) : [],
    [item],
  );
  const differing = rows.filter((r) => r.differs);
  const shown = showAll ? rows : differing;

  if (!mounted || !item) return null;

  // A hand-made mapping carries verdict='identical', confidence=1.0 written by
  // the endpoint, not by a model. Presenting that as an AI verdict would be a
  // lie, so this is the one distinction the drawer leads with.
  const handMapped = item.judge_model === "manual";
  const basisMismatch = item.rayna_basis !== item.competitor_basis;
  // Catches a pair pointed at the wrong Rayna product — the field diff can't,
  // because Rayna's feed fingerprint carries no `venue` to compare against.
  const venueOdd = venueLooksUnrelated(
    item.competitor_fingerprint.venue,
    item.product_name,
    item.product_city,
  );

  const rAed = toAED(item.rayna_price, item.rayna_currency);
  const cAed = toAED(item.competitor_price, item.competitor_currency);
  const gapPct =
    rAed != null && cAed != null && rAed !== 0 ? ((cAed - rAed) / rAed) * 100 : null;

  const age = daysSince(item.listing_scraped_at);
  const staleTone =
    age == null || age < STALE_WARN_DAYS
      ? "ok"
      : age < STALE_BAD_DAYS
        ? "warn"
        : "bad";

  const notes = cleanNotes(item.diff_notes);

  return createPortal(
    <div
      className="fixed inset-0 z-[90] flex justify-end bg-black/35 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <aside
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Match evidence for ${item.seller_domain}`}
        className="w-full max-w-[560px] h-full bg-white shadow-2xl flex flex-col animate-[slideIn_.18s_ease-out]"
      >
        {/* ---- Header ---- */}
        <header className="px-5 py-4 border-b border-[#E4E7EC] flex items-start justify-between gap-3 shrink-0">
          <div className="min-w-0">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-[#98A2B3]">
              Why this is a match
            </div>
            <div className="text-[16px] font-bold text-[#101828] mt-1 truncate">
              Rayna vs {item.seller_domain}
            </div>
            <div className="text-[12px] text-[#667085] mt-0.5 truncate">
              {item.product_name}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="p-1.5 rounded-[8px] text-[#98A2B3] hover:text-[#101828] hover:bg-[#F2F4F7] transition shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5">
          {/* ---- Verdict / provenance ---- */}
          {handMapped ? (
            <div className="border border-[#FEDF89] bg-[#FFFAEB] rounded-[10px] px-4 py-3 flex items-start gap-2.5">
              <UserCheck className="w-4 h-4 text-[#B54708] mt-0.5 shrink-0" />
              <div className="text-[12.5px] text-[#7A4F08] leading-relaxed">
                <span className="font-semibold">Linked by hand.</span> A reviewer
                mapped these two options directly — the adjudicator never
                compared them, so there is no model verdict or confidence score
                behind this pair. Check the fields below yourself.
              </div>
            </div>
          ) : (
            <div className="border border-[#E4E7EC] rounded-[10px] px-4 py-3">
              <div className="flex items-center gap-2 flex-wrap">
                <VerdictChip verdict={item.verdict} />
                <span className="text-[12px] text-[#667085] tnum">
                  confidence{" "}
                  <span className="font-semibold text-[#344054]">
                    {item.confidence.toFixed(2)}
                  </span>
                </span>
                {item.confidence < 0.7 && (
                  <span className="text-[11px] font-semibold text-[#B54708]">
                    below review threshold
                  </span>
                )}
              </div>
              {notes && (
                <p className="text-[12.5px] text-[#344054] leading-relaxed mt-2.5">
                  {notes}
                </p>
              )}
            </div>
          )}

          {/* ---- Cross-product sanity check ---- */}
          {venueOdd && (
            <div className="border border-[#FECACA] bg-[#FEF2F2] rounded-[10px] px-4 py-3 flex items-start gap-2.5">
              <AlertTriangle className="w-4 h-4 text-[#B42318] mt-0.5 shrink-0" />
              <div className="text-[12.5px] text-[#7A271A] leading-relaxed">
                <span className="font-semibold">Worth checking.</span> The seller
                lists this option&rsquo;s venue as{" "}
                <span className="font-semibold">
                  {String(item.competitor_fingerprint.venue)}
                </span>
                , which shares no wording with{" "}
                <span className="font-semibold">{item.product_name}</span>
                {item.product_city ? ` in ${item.product_city}` : ""}. These may
                not be the same experience — a venue name is weak evidence, so
                confirm against the listing before trusting the gap.
              </div>
            </div>
          )}

          {/* ---- Price ---- */}
          <section>
            <SectionLabel>Price</SectionLabel>
            <div className="border border-[#E4E7EC] rounded-[10px] overflow-hidden">
              <PriceRow
                who="Rayna"
                name={item.rayna_option_name}
                price={item.rayna_price}
                currency={item.rayna_currency}
                basis={item.rayna_basis}
                source={item.rayna_date_price_source}
              />
              <PriceRow
                who={item.seller_domain}
                name={item.competitor_option_name}
                price={item.competitor_price}
                currency={item.competitor_currency}
                basis={item.competitor_basis}
                source={item.competitor_date_price_source}
                bordered
              />
              <div className="px-4 py-2.5 bg-[#F9FAFB] border-t border-[#E4E7EC] flex items-center justify-between gap-3">
                <span className="text-[11.5px] font-semibold uppercase tracking-[0.06em] text-[#667085]">
                  Gap
                </span>
                {basisMismatch ? (
                  <span className="text-[12px] font-semibold text-[#B54708]">
                    not comparable — bases differ
                  </span>
                ) : gapPct == null ? (
                  <span className="text-[12px] text-[#98A2B3]">
                    no price on one side
                  </span>
                ) : (
                  <span
                    className={`tnum text-[13px] font-bold ${
                      gapPct > 0.5
                        ? "text-[#067647]"
                        : gapPct < -0.5
                          ? "text-[#B42318]"
                          : "text-[#475467]"
                    }`}
                  >
                    {gapPct > 0 ? "+" : ""}
                    {gapPct.toFixed(1)}%{" "}
                    <span className="font-medium text-[#667085]">
                      {gapPct > 0.5
                        ? "we're cheaper"
                        : gapPct < -0.5
                          ? "we're pricier"
                          : "at par"}
                    </span>
                  </span>
                )}
              </div>
            </div>

            {basisMismatch && (
              <div className="mt-2 flex items-start gap-2 text-[11.5px] text-[#B54708]">
                <AlertTriangle className="w-3.5 h-3.5 mt-[1px] shrink-0" />
                <span>
                  Rayna prices this {fmtBasis(item.rayna_basis)}; the seller
                  prices it {fmtBasis(item.competitor_basis)}. The percentage
                  above is arithmetic, not a like-for-like comparison.
                </span>
              </div>
            )}
          </section>

          {/* ---- Field comparison ---- */}
          <section>
            <SectionLabel>
              {differing.length === 0
                ? "Fields"
                : `${differing.length} field${differing.length === 1 ? "" : "s"} differ`}
            </SectionLabel>

            {shown.length === 0 ? (
              <div className="border border-dashed border-[#D0D5DD] rounded-[10px] px-4 py-6 text-center text-[12.5px] text-[#667085]">
                {rows.length === 0
                  ? "Neither side recorded comparable fields."
                  : "No stated field differs between the two options."}
              </div>
            ) : (
              <div className="border border-[#E4E7EC] rounded-[10px] overflow-hidden">
                <table className="w-full text-[12.5px]">
                  <thead>
                    <tr className="bg-[#F9FAFB] text-[#98A2B3] text-[10px] uppercase tracking-[0.06em]">
                      <th className="text-left px-3 py-2 font-semibold w-[28%]">
                        Field
                      </th>
                      <th className="text-left px-3 py-2 font-semibold">Rayna</th>
                      <th className="text-left px-3 py-2 font-semibold">Seller</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F2F4F7]">
                    {shown.map((r) => (
                      <tr key={r.label} className={r.differs ? "bg-[#FFFAEB]" : ""}>
                        <td className="px-3 py-2 text-[#667085] font-medium align-top">
                          {r.label}
                        </td>
                        <td className="px-3 py-2 text-[#344054] align-top">
                          {r.rayna}
                        </td>
                        <td
                          className={`px-3 py-2 align-top ${
                            r.differs
                              ? "text-[#101828] font-semibold"
                              : "text-[#344054]"
                          }`}
                        >
                          {r.competitor}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {rows.length > differing.length && (
              <button
                type="button"
                onClick={() => setShowAll((v) => !v)}
                className="mt-2 text-[12px] font-semibold text-[#EA580C] hover:text-[#C2410C] transition"
              >
                {showAll
                  ? "Show only differences"
                  : `Show all ${rows.length} fields`}
              </button>
            )}

            {rows.length > 0 && differing.length < rows.length && (
              <div className="mt-2 flex items-start gap-2 text-[11.5px] text-[#98A2B3]">
                <Info className="w-3.5 h-3.5 mt-[1px] shrink-0" />
                <span>
                  A field only counts as a difference when both sides stated a
                  value. Blanks mean the seller&rsquo;s page didn&rsquo;t say.
                </span>
              </div>
            )}
          </section>

          {/* ---- Provenance ---- */}
          <section>
            <SectionLabel>Source</SectionLabel>
            <dl className="border border-[#E4E7EC] rounded-[10px] divide-y divide-[#F2F4F7] text-[12.5px]">
              <MetaRow label="Captured">
                <span
                  className={
                    staleTone === "bad"
                      ? "text-[#B42318] font-semibold"
                      : staleTone === "warn"
                        ? "text-[#B54708] font-semibold"
                        : "text-[#344054]"
                  }
                >
                  {fmtWhen(item.listing_scraped_at)}
                  {age != null && (
                    <> · {age === 0 ? "today" : `${age}d ago`}</>
                  )}
                </span>
              </MetaRow>
              <MetaRow label="Mapped by">
                {item.created_by_email ? (
                  <span
                    className="text-[#344054]"
                    title={item.created_by_email}
                  >
                    {item.created_by_name ?? item.created_by_email}
                  </span>
                ) : (
                  <span
                    className="text-[#98A2B3]"
                    title="Created before per-user attribution existed, or by an account since deleted"
                  >
                    not recorded
                  </span>
                )}
              </MetaRow>
              <MetaRow label="Judged by">
                <span className="text-[#344054] font-mono text-[11.5px]">
                  {handMapped ? "human reviewer" : item.judge_model ?? "—"}
                </span>
              </MetaRow>
              <MetaRow label="Listing">
                <a
                  href={item.listing_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-[#EA580C] hover:text-[#C2410C] font-semibold"
                >
                  Open on {item.seller_domain}
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              </MetaRow>
            </dl>

            {staleTone !== "ok" && (
              <div className="mt-2 flex items-start gap-2 text-[11.5px] text-[#B54708]">
                <AlertTriangle className="w-3.5 h-3.5 mt-[1px] shrink-0" />
                <span>
                  This price was captured {age}&nbsp;days ago. Re-check the
                  listing before acting on the gap.
                </span>
              </div>
            )}
          </section>
        </div>
      </aside>

      <style>{`
        @keyframes slideIn {
          from { transform: translateX(16px); opacity: .6 }
          to   { transform: translateX(0);    opacity: 1 }
        }
      `}</style>
    </div>,
    document.body,
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-[#98A2B3] mb-2">
      {children}
    </div>
  );
}

function MetaRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="px-4 py-2.5 flex items-center justify-between gap-3">
      <dt className="text-[#667085]">{label}</dt>
      <dd className="text-right min-w-0 truncate">{children}</dd>
    </div>
  );
}

function VerdictChip({ verdict }: { verdict: MappedItem["verdict"] }) {
  const styles = {
    identical: { color: "#166534", bg: "#F0FDF4", border: "#BBF7D0", label: "identical" },
    near: { color: "#92400E", bg: "#FFFAEB", border: "#FEDF89", label: "near match" },
    different: { color: "#991B1B", bg: "#FEF2F2", border: "#FECACA", label: "different" },
  } as const;
  const s = styles[verdict] ?? styles.different;
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-[3px] rounded-full text-[11.5px] font-semibold border"
      style={{ color: s.color, background: s.bg, borderColor: s.border }}
    >
      <ShieldCheck className="w-3.5 h-3.5" />
      {s.label}
    </span>
  );
}

function PriceRow({
  who,
  name,
  price,
  currency,
  basis,
  source,
  bordered,
}: {
  who: string;
  name: string;
  price: number | null;
  currency: string | null;
  basis: string;
  source?: "observation" | "default" | null;
  bordered?: boolean;
}) {
  const cur = (currency || "AED").toUpperCase();
  return (
    <div
      className={`px-4 py-3 flex items-start justify-between gap-4 ${
        bordered ? "border-t border-[#F2F4F7]" : ""
      }`}
    >
      <div className="min-w-0">
        <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[#98A2B3]">
          {who}
        </div>
        <div className="text-[12.5px] text-[#344054] mt-0.5 leading-snug">
          {name}
        </div>
        <div className="text-[11px] text-[#98A2B3] mt-0.5 font-mono">
          {fmtBasis(basis)}
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="tnum text-[15px] font-bold text-[#101828]">
          {fmtAED(price, currency)}
        </div>
        {price != null && cur !== "AED" && (
          <div className="tnum text-[10.5px] text-[#98A2B3]">
            quoted {fmtMoney(price, currency)}
          </div>
        )}
        {source === "default" && (
          <div className="text-[10px] text-[#B54708] font-semibold mt-0.5">
            default price
          </div>
        )}
      </div>
    </div>
  );
}
