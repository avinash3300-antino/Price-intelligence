export function fmtMoney(amount: number | null | undefined, currency?: string | null): string {
  if (amount == null) return "—";
  const cur = currency ?? "AED";
  const formatted = amount.toLocaleString("en-AE", {
    maximumFractionDigits: 2,
    minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
  });
  return `${cur} ${formatted}`;
}

// FX rates → AED. AED is pegged to USD at 3.6725; others are mid-market
// approximations used for display only (the real pipeline normalises to AED
// upstream, so this is a UI-layer safety net for any rows that slip through
// in foreign currency).
const FX_TO_AED: Record<string, number> = {
  AED: 1,
  USD: 3.6725,
  EUR: 3.99,
  GBP: 4.66,
  INR: 0.044,
  SAR: 0.98,
  THB: 0.103,
  IDR: 0.000226,
  MYR: 0.79,
  SGD: 2.74,
};

export function toAED(price: number | null | undefined, currency: string | null | undefined): number | null {
  if (price == null) return null;
  const code = (currency || "AED").toUpperCase();
  const rate = FX_TO_AED[code] ?? 1;
  return price * rate;
}

export function fmtAED(price: number | null | undefined, currency: string | null | undefined): string {
  const aed = toAED(price, currency);
  if (aed == null) return "—";
  return fmtMoney(aed, "AED");
}

export function fmtPercent(pct: number, opts: { sign?: boolean } = {}): string {
  const sign = opts.sign && pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

export function fmtBasis(basis: string): string {
  return basis.replace(/_/g, " ");
}

export function fmtConfidence(c: number): string {
  return c.toFixed(2);
}

export function fmtField(v: unknown): { text: string; missing: boolean } {
  if (v == null || v === "") return { text: "not stated", missing: true };
  if (Array.isArray(v)) {
    if (v.length === 0) return { text: "not stated", missing: true };
    return { text: v.join(", "), missing: false };
  }
  if (typeof v === "boolean") return { text: v ? "yes" : "no", missing: false };
  return { text: String(v), missing: false };
}

export function relativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  const diff = Date.now() - t;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return new Date(iso).toLocaleDateString("en-GB");
}
