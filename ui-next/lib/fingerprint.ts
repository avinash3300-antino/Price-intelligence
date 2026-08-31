/**
 * Shared fingerprint field map.
 *
 * Rayna and competitor fingerprints don't use the same keys — the Vercel feed
 * writes `cancellation_text` where the Claude extractor writes
 * `cancellation_window_hours`, and the feed carries internal ids (group_id,
 * vercel_option_id) that mean nothing to a reviewer. This module resolves both
 * sides onto one labelled row set, so /compare and the evidence drawer can't
 * drift apart.
 */

export interface FieldRow {
  label: string;
  raynaKeys: string[];
  compKeys: string[];
  format?: (v: unknown) => unknown;
}

export const DURATION_FMT = (v: unknown) => {
  if (typeof v === "number") return `${v} min`;
  return v;
};

export const HOURS_FMT = (v: unknown) => {
  if (typeof v === "number") return `≤ ${v} hrs`;
  return v;
};

export const FIELDS: FieldRow[] = [
  { label: "Pricing basis", raynaKeys: ["pricing_basis"], compKeys: ["pricing_basis"] },
  { label: "Tier", raynaKeys: ["tier"], compKeys: ["tier"] },
  { label: "Venue", raynaKeys: ["venue"], compKeys: ["venue"] },
  {
    label: "Category",
    raynaKeys: ["activity_category"],
    compKeys: ["activity_category", "category"],
  },
  {
    label: "Duration",
    raynaKeys: ["duration_minutes", "duration_label"],
    compKeys: ["duration_minutes", "duration_label"],
    format: DURATION_FMT,
  },
  {
    label: "Transfer included",
    raynaKeys: ["transfer_included"],
    compKeys: ["transfer_included"],
  },
  {
    label: "Transfer type",
    raynaKeys: ["transfer_type"],
    compKeys: ["transfer_type"],
  },
  {
    label: "Meal included",
    raynaKeys: ["meal_included"],
    compKeys: ["meal_included"],
  },
  { label: "Meal type", raynaKeys: ["meal_type"], compKeys: ["meal_type"] },
  { label: "Min pax", raynaKeys: ["group_min"], compKeys: ["group_min"] },
  { label: "Max pax", raynaKeys: ["group_max"], compKeys: ["group_max"] },
  { label: "Languages", raynaKeys: ["languages"], compKeys: ["languages"] },
  {
    label: "Cancellation",
    raynaKeys: ["cancellation_window_hours", "cancellation_text"],
    compKeys: ["cancellation_window_hours", "cancellation_text"],
    format: HOURS_FMT,
  },
  { label: "Highlights", raynaKeys: ["highlights"], compKeys: ["highlights"] },
  { label: "Inclusions", raynaKeys: ["inclusions"], compKeys: ["inclusions"] },
  { label: "Exclusions", raynaKeys: ["exclusions"], compKeys: ["exclusions"] },
  { label: "Notes", raynaKeys: ["notes"], compKeys: ["notes"] },
];

export const VENDOR_KEYS = new Set([
  "vendor",
  "gt_product_id",
  "headout_variant_id",
  "headout_product_id",
  "vercel_option_id",
  "group_id",
  "merchant",
  "city",
]);

export function pickFirst(
  fp: Record<string, unknown>,
  keys: string[],
): unknown {
  for (const k of keys) {
    const v = fp[k];
    if (v == null) continue;
    if (Array.isArray(v) && v.length === 0) continue;
    if (v === "") continue;
    return v;
  }
  return null;
}

export function hasMeaningfulData(fp: Record<string, unknown>): boolean {
  for (const row of FIELDS) {
    if (row.label === "Pricing basis" || row.label === "Tier") continue;
    if (pickFirst(fp, row.compKeys) != null) return true;
  }
  return false;
}


/** One resolved comparison row, both sides already formatted to a display string. */
export interface DiffRow {
  label: string;
  rayna: string;
  competitor: string;
  differs: boolean;
}

function display(v: unknown): string {
  if (v == null || v === "") return "—";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

/**
 * Resolve both fingerprints onto the shared field map.
 *
 * A row is only `differs` when both sides actually stated something and the
 * values disagree — "competitor didn't say" is missing data, not a difference,
 * and calling it one is exactly the overclaiming the adjudicator prompt bans.
 */
export function diffRows(
  rayna: Record<string, unknown>,
  competitor: Record<string, unknown>,
): DiffRow[] {
  return FIELDS.map((f) => {
    const rv = pickFirst(rayna, f.raynaKeys);
    const cv = pickFirst(competitor, f.compKeys);
    const r = display(f.format && rv != null ? f.format(rv) : rv);
    const c = display(f.format && cv != null ? f.format(cv) : cv);
    return {
      label: f.label,
      rayna: r,
      competitor: c,
      differs: r !== "—" && c !== "—" && r !== c,
    };
  }).filter((row) => row.rayna !== "—" || row.competitor !== "—");
}

/**
 * Words that carry no identifying signal in a product or venue name.
 * Kept deliberately small — over-stripping turns a real venue into an empty
 * token set, which would fire the check on everything.
 */
const ANCHOR_STOPWORDS = new Set([
  "the", "and", "in", "at", "of", "a", "an", "with", "for", "to", "by", "from",
  "tickets", "ticket", "tour", "tours", "pass", "entry", "experience",
  "combo", "package", "deal", "offer", "ride", "trip", "visit",
]);

function anchorTokens(s: string | null | undefined): Set<string> {
  return new Set(
    (s ?? "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .split(" ")
      .filter((t) => t.length > 2 && !ANCHOR_STOPWORDS.has(t)),
  );
}

/**
 * Soft cross-product check: does the competitor's stated venue share any
 * identifying word with the Rayna product it's mapped under?
 *
 * This exists because a competitor's fingerprint carries `venue` but Rayna's
 * feed fingerprint usually doesn't — so a field-by-field diff can't catch a
 * mapping pointed at the wrong product. The anchor product name is the only
 * ground truth available on that side.
 *
 * Returns false whenever it cannot tell (no venue recorded, no usable tokens).
 * A venue string is weak evidence, so callers must present a hit as "worth
 * checking", never as a verdict.
 */
export function venueLooksUnrelated(
  competitorVenue: unknown,
  productName: string,
  productCity?: string | null,
): boolean {
  if (typeof competitorVenue !== "string" || !competitorVenue.trim()) return false;
  const venue = anchorTokens(competitorVenue);
  const anchor = anchorTokens(productName);
  for (const t of anchorTokens(productCity)) anchor.add(t);
  if (venue.size === 0 || anchor.size === 0) return false;
  for (const t of venue) if (anchor.has(t)) return false;
  return true;
}
