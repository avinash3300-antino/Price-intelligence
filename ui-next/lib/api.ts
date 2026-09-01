/**
 * Client for the FastAPI backend at :8001.
 * All fetches happen in server components (no-store cache).
 *
 * NEXT_PUBLIC_API_URL overrides the base URL if set, useful for prod.
 */

// Server-side (Node, inside the web container during SSR) needs an absolute
// URL — Node's fetch rejects relative paths.
//
// Browser-side is always same-origin, deliberately not configurable. The
// session cookie is httpOnly and SameSite=Lax, so pointing the browser at
// another origin means it is never sent and every request comes back 401.
// Same origin is served by nginx in production and by the /api rewrite in
// next.config.ts during development.
const API_BASE =
  typeof window === "undefined"
    ? process.env.API_URL_INTERNAL ?? "http://localhost:8001"
    : "";

/** Thrown when the API rejects the session. Pages catch this and redirect. */
export class UnauthenticatedError extends Error {
  constructor(public readonly path: string) {
    super(`Not signed in (${path})`);
    this.name = "UnauthenticatedError";
  }
}

/** Thrown when signed in but lacking the permission for this endpoint. */
export class ForbiddenError extends Error {
  constructor(public readonly path: string, public readonly detail: string) {
    super(detail || `Forbidden (${path})`);
    this.name = "ForbiddenError";
  }
}

/**
 * Forward the caller's session cookie on server-side fetches.
 *
 * Server components run in Node and get their own fetch, with no browser to
 * attach cookies — so the incoming request's cookies have to be copied across
 * by hand or every SSR call arrives unauthenticated. `next/headers` is
 * imported dynamically because this module is also pulled into the client
 * bundle, where that import does not exist.
 */
async function serverCookieHeader(): Promise<Record<string, string>> {
  if (typeof window !== "undefined") return {};
  try {
    const { cookies } = await import("next/headers");
    const jar = await cookies();
    const header = jar.toString();
    return header ? { cookie: header } : {};
  } catch {
    // Called outside a request scope (build-time prerender): nothing to send.
    return {};
  }
}

async function api<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    headers: await serverCookieHeader(),
    credentials: "include",
  });
  if (r.status === 401) throw new UnauthenticatedError(path);
  if (r.status === 403) {
    let detail = "";
    try {
      detail = (await r.json())?.detail ?? "";
    } catch {
      /* not JSON */
    }
    throw new ForbiddenError(path, detail);
  }
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`API ${r.status} on ${path}: ${body.slice(0, 200)}`);
  }
  return r.json() as Promise<T>;
}

export interface SessionScope {
  country: string;
  city: string | null;
}

export interface SessionUser {
  id: number;
  email: string;
  full_name: string;
  role: "admin" | "user";
  is_owner: boolean;
  must_change_password: boolean;
  permissions: string[];
  scopes: SessionScope[];
}

export function getMe(): Promise<SessionUser> {
  return api<SessionUser>("/api/auth/me");
}

// ---------- Types (snake_case to match Python API) ----------

export interface Product {
  id: number;
  name: string;
  type: string | null;
  city: string | null;
  country: string | null;
  market: string;
  currency: string;
  url: string | null;
}

export interface CheapestCompetitor {
  domain: string;
  price: number;
  currency: string;
  gap_aed: number;
  gap_pct: number;
  rayna_price: number;
}

export interface RaynaPriceSummary {
  min_price: number | null;
  max_price: number | null;
  currency: string | null;
  priced_count: number;
  unpriced_count: number;
  pricing_basis: string | null;
}

export interface DashboardStat {
  product: Product;
  option_count: number;
  seller_count: number;
  comparable_count: number;
  options_mapped_count: number;
  rayna_price: RaynaPriceSummary;
  cheapest_competitor: CheapestCompetitor | null;
}

export interface PipelineStats {
  products: number;
  rayna_options: number;
  competitors: number;
  scraped_listings: number;
  competitor_options: number;
  mappings: number;
  identical: number;
  near: number;
  different: number;
  needs_review: number;
}

export interface DashboardPayload {
  pipeline: PipelineStats;
  products: DashboardStat[];
}

export interface RaynaOption {
  id: number;
  name: string;
  pricing_basis: string;
  price: number | null;
  currency: string | null;
  market: string;
  fingerprint: Record<string, unknown>;
  // Present only when mapping-workspace was fetched with ?date=YYYY-MM-DD.
  date_price_source?: "observation" | "default" | null;
}

export interface MappedCompetitorOption {
  mapping_id: number;
  verdict: "identical" | "near" | "different";
  confidence: number;
  diff_notes: string;
  competitor_option_id: number;
  seller_domain: string;
  listing_url: string;
  name: string;
  pricing_basis: string;
  price: number | null;
  currency: string | null;
  fingerprint: Record<string, unknown>;
}

export interface RaynaOptionWithMappings {
  option: RaynaOption;
  mappings: MappedCompetitorOption[];
}

export interface ProductComparison {
  product: Product;
  options: RaynaOptionWithMappings[];
}

export interface CompetitorOptionForMapping {
  option_id: number;
  name: string;
  pricing_basis: string;
  price: number | null;
  currency: string | null;
  tier: string | null;
  listing_url: string;
  fingerprint: Record<string, unknown>;
  mapping: {
    mapping_id: number;
    rayna_option_id: number;
    rayna_option_name: string;
  } | null;
  date_price_source?: "observation" | "default" | null;
}

export interface SellerGroup {
  seller_domain: string;
  competitor_id: number;
  listing_count: number;
  options: CompetitorOptionForMapping[];
}

export interface ProductMappingPayload {
  product: Product;
  rayna_options: RaynaOption[];
  sellers: SellerGroup[];
  total_competitor_options: number;
}

export interface OptionListItem {
  option_id: number;
  name: string;
  pricing_basis: string;
  price: number | null;
  currency: string | null;
  fingerprint: Record<string, unknown>;
  product_id: number;
  product_name: string;
  product_city: string | null;
  product_country: string | null;
  product_type: string | null;
  seller_count: number;
  mapped_count: number;
}

export interface ManualMapResponse {
  mapping_id: number;
  rayna_option_id: number;
  competitor_option_id: number;
  created_at: string;
  is_manual: boolean;
}

export interface MappedItem {
  mapping_id: number;
  product_id: number;
  product_name: string;
  product_country: string | null;
  product_city: string | null;
  product_url: string | null;
  rayna_option_id: number;
  rayna_option_name: string;
  rayna_price: number | null;
  rayna_currency: string | null;
  rayna_basis: string;
  competitor_option_id: number;
  competitor_option_name: string;
  competitor_price: number | null;
  competitor_currency: string | null;
  competitor_basis: string;
  seller_domain: string;
  listing_url: string;
  created_at: string;
  // Present only when getMapped(date) was called with a date param.
  rayna_date_price_source?: "observation" | "default" | null;
  competitor_date_price_source?: "observation" | "default" | null;
  // Evidence for why this pair is treated as a match. `judge_model === "manual"`
  // means a human linked it by hand and the adjudicator never saw it — the
  // verdict/confidence on those rows are placeholders, not a model's opinion.
  verdict: "identical" | "near" | "different";
  confidence: number;
  diff_notes: string;
  judge_model: string | null;
  is_manual: boolean;
  human_reviewed: boolean;
  rayna_fingerprint: Record<string, unknown>;
  competitor_fingerprint: Record<string, unknown>;
  listing_scraped_at: string | null;
  competitor_last_checked_at: string | null;
  competitor_last_seen_at: string | null;
  created_by_email: string | null;
  created_by_name: string | null;
}

export interface ReviewItem {
  mapping_id: number;
  product_id: number;
  product_name: string;
  product_url: string | null;
  product_country: string | null;
  product_city: string | null;
  rayna_option_id: number | null;
  rayna_option_name: string;
  rayna_price: number | null;
  rayna_currency: string | null;
  rayna_basis: string;
  competitor_option_name: string;
  competitor_price: number | null;
  competitor_currency: string | null;
  competitor_basis: string;
  seller_domain: string;
  verdict: "identical" | "near" | "different";
  confidence: number;
  diff_notes: string;
  reasons: string[];
}

// ---------- Endpoints ----------

export function getDashboard(): Promise<DashboardPayload> {
  return api<DashboardPayload>("/api/dashboard");
}

export function getProductComparison(productId: number): Promise<ProductComparison> {
  return api<ProductComparison>(`/api/products/${productId}/comparison`);
}

export function getReviewQueue(): Promise<ReviewItem[]> {
  return api<ReviewItem[]>("/api/review-queue");
}

export function getHealth(): Promise<{ ok: boolean; db: string; db_exists: boolean }> {
  return api("/api/health");
}

export function getMappingWorkspace(
  productId: number,
  date?: string | null,
): Promise<ProductMappingPayload> {
  const suffix = date ? `?date=${encodeURIComponent(date)}` : "";
  return api<ProductMappingPayload>(`/api/products/${productId}/mapping-workspace${suffix}`);
}

export function getOptionsByLocation(
  country: string,
  city: string,
): Promise<OptionListItem[]> {
  const qs = new URLSearchParams({ country, city }).toString();
  return api<OptionListItem[]>(`/api/options/by-location?${qs}`);
}

export function getMapped(date?: string | null): Promise<MappedItem[]> {
  const suffix = date ? `?date=${encodeURIComponent(date)}` : "";
  return api<MappedItem[]>(`/api/mapped${suffix}`);
}

export const API_BASE_PUBLIC = API_BASE;

export interface ExtractedCompetitorOption {
  competitor_option_id: number;
  name: string;
  price: number | null;
  currency: string | null;
  pricing_basis: string;
  verdict: "identical" | "near" | "different" | null;
  confidence: number | null;
  diff_notes: string | null;
  mapping_id: number | null;
  is_target: boolean;
}

export interface AddByUrlResponse {
  mapping_id: number | null;
  rayna_option_id: number;
  competitor_option_id: number;
  seller_domain: string;
  listing_url: string;
  verdict: "identical" | "near" | "different";
  confidence: number;
  diff_notes: string;
  saved_mapping: boolean;
  competitor_name: string;
  competitor_price: number | null;
  competitor_currency: string | null;
  competitor_pricing_basis: string;
  all_options: ExtractedCompetitorOption[];
}

export type AddByUrlOutcome =
  | { kind: "ok"; data: AddByUrlResponse }
  | { kind: "needs_paste"; message: string } // 422 — direct fetch failed, ask user to paste content
  | { kind: "error"; status: number; message: string };

export async function addCompetitorByUrl(input: {
  rayna_option_id: number;
  url: string;
  pasted_content?: string;
  note?: string;
}): Promise<AddByUrlOutcome> {
  const r = await fetch(`${API_BASE}/api/mappings/from-url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (r.ok) {
    const data = (await r.json()) as AddByUrlResponse;
    return { kind: "ok", data };
  }
  let detail = `HTTP ${r.status}`;
  try {
    const body = await r.json();
    if (body && typeof body.detail === "string") detail = body.detail;
  } catch {
    /* not JSON */
  }
  if (r.status === 422) return { kind: "needs_paste", message: detail };
  return { kind: "error", status: r.status, message: detail };
}
