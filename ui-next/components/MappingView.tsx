"use client";

import { useEffect, useMemo, useRef, useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createPortal } from "react-dom";
import {
  ArrowLeftRight,
  Calendar,
  Check,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Globe,
  Link as LinkIcon,
  Loader2,
  MapPin,
  Plus,
  Search,
  X,
} from "lucide-react";
import { fmtMoney, fmtBasis, fmtAED } from "@/lib/format";
import {
  API_BASE_PUBLIC,
  type DashboardStat,
  type ProductMappingPayload,
  type CompetitorOptionForMapping,
  type RaynaOption,
  type OptionListItem,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { AddCompetitorByUrlModal } from "@/components/AddCompetitorByUrlModal";

interface Props {
  initialProducts: DashboardStat[];
}

/* -------------------- emoji + flag helpers -------------------- */

const FLAGS: Record<string, string> = {
  "United Arab Emirates": "🇦🇪",
  Thailand: "🇹🇭",
  Malaysia: "🇲🇾",
  India: "🇮🇳",
  Indonesia: "🇮🇩",
  Philippines: "🇵🇭",
  Singapore: "🇸🇬",
  "Saudi Arabia": "🇸🇦",
  Italy: "🇮🇹",
  Spain: "🇪🇸",
  Georgia: "🇬🇪",
  Japan: "🇯🇵",
  Azerbaijan: "🇦🇿",
  Armenia: "🇦🇲",
  Vietnam: "🇻🇳",
  Egypt: "🇪🇬",
  Turkey: "🇹🇷",
  Sri_Lanka: "🇱🇰",
  "Sri Lanka": "🇱🇰",
  Maldives: "🇲🇻",
  Mauritius: "🇲🇺",
  Kenya: "🇰🇪",
  Oman: "🇴🇲",
  Bahrain: "🇧🇭",
  Qatar: "🇶🇦",
  Jordan: "🇯🇴",
  Morocco: "🇲🇦",
  Greece: "🇬🇷",
  Switzerland: "🇨🇭",
  France: "🇫🇷",
  Germany: "🇩🇪",
  "United Kingdom": "🇬🇧",
  Australia: "🇦🇺",
  Nepal: "🇳🇵",
};

function flagFor(country: string | null | undefined): string {
  if (!country) return "🌍";
  return FLAGS[country] ?? "🌍";
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s;
}

function emojiForProduct(name: string): string {
  const n = (name || "").toLowerCase();
  if (n.includes("burj")) return "🌆";
  if (n.includes("yacht")) return "⛵";
  if (n.includes("desert") || n.includes("dune") || n.includes("safari")) return "🏜";
  if (n.includes("dinner")) return "🍽";
  if (n.includes("fish")) return "🎣";
  if (n.includes("camel")) return "🐪";
  if (n.includes("city tour") || n.includes("sightseeing")) return "🚌";
  if (n.includes("visa")) return "📘";
  if (n.includes("cruise")) return "🚢";
  if (n.includes("hotel") || n.includes("resort")) return "🏨";
  if (n.includes("museum") || n.includes("gallery")) return "🏛";
  if (n.includes("park") || n.includes("water")) return "🌊";
  return "📍";
}

/* ==============================================================
   MappingView — single-page split layout.
   Top: compact Country + City selectors.
   Below: 3-column grid — Products list · Options list · Competitors.
   Picking an option populates the right pane immediately.
   ============================================================== */

export function MappingView({ initialProducts }: Props) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  // Hydrate initial state from the URL so the workspace survives refresh —
  // country + city + product + option + date all round-trip through the URL.
  // This also keeps a shareable link ("open this exact selection") working.
  const initialProduct = useMemo<DashboardStat | null>(() => {
    const raw = searchParams?.get("productId");
    if (!raw) return null;
    const pid = parseInt(raw, 10);
    if (!Number.isFinite(pid)) return null;
    return initialProducts.find((p) => p.product.id === pid) ?? null;
  }, [searchParams, initialProducts]);

  const initialRaynaOptionId = useMemo<number | null>(() => {
    const raw = searchParams?.get("raynaOptionId");
    if (!raw) return null;
    const n = parseInt(raw, 10);
    return Number.isFinite(n) ? n : null;
  }, [searchParams]);

  const initialCountry =
    searchParams?.get("country") ??
    initialProduct?.product.country ??
    null;
  const initialCity =
    searchParams?.get("city") ?? initialProduct?.product.city ?? null;
  const initialDate = (() => {
    const raw = searchParams?.get("date");
    if (raw && /^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
    return new Date().toISOString().slice(0, 10);
  })();

  const [country, setCountry] = useState<string | null>(initialCountry);
  const [city, setCity] = useState<string | null>(initialCity);
  const [chosenProduct, setChosenProduct] = useState<DashboardStat | null>(
    initialProduct,
  );
  const [chosenOption, setChosenOption] = useState<OptionListItem | null>(null);
  // Default to today's date so prices reflect a real bookable date immediately;
  // user can change to any date within the next 60 days.
  const [chosenDate, setChosenDate] = useState<string>(initialDate);

  // Sync state → URL on every change. Using router.replace (not push) so
  // navigation history doesn't fill up with intermediate selections. Empty
  // params are omitted for a cleaner URL.
  useEffect(() => {
    const qs = new URLSearchParams();
    if (country) qs.set("country", country);
    if (city) qs.set("city", city);
    if (chosenProduct) qs.set("productId", String(chosenProduct.product.id));
    if (chosenOption) qs.set("raynaOptionId", String(chosenOption.option_id));
    if (chosenDate) qs.set("date", chosenDate);
    const next = qs.toString() ? `${pathname}?${qs.toString()}` : pathname;
    router.replace(next, { scroll: false });
  }, [country, city, chosenProduct, chosenOption, chosenDate, pathname, router]);

  function selectCountry(c: string | null) {
    setCountry(c);
    setCity(null);
    setChosenProduct(null);
    setChosenOption(null);
  }
  function selectCity(c: string | null) {
    setCity(c);
    setChosenProduct(null);
    setChosenOption(null);
  }
  function selectProduct(p: DashboardStat | null) {
    setChosenProduct(p);
    setChosenOption(null);
  }

  return (
    <div className="max-w-[1560px] mx-auto w-full flex flex-col flex-1 min-h-0">
      <SelectorBar
        products={initialProducts}
        country={country}
        onCountry={selectCountry}
        city={city}
        onCity={selectCity}
        date={chosenDate}
        onDate={setChosenDate}
      />

      <div
        className="grid gap-3 mt-4 flex-1 min-h-0"
        style={{ gridTemplateColumns: "300px 360px minmax(0, 1fr)" }}
      >
        <ProductPanel
          products={initialProducts}
          country={country}
          city={city}
          chosenProductId={chosenProduct?.product.id ?? null}
          onPick={selectProduct}
        />
        <OptionPanel
          country={country}
          city={city}
          product={chosenProduct}
          chosenOptionId={chosenOption?.option_id ?? null}
          onPick={setChosenOption}
          autoSelectOptionId={initialRaynaOptionId}
        />
        <RightPane chosenOption={chosenOption} chosenDate={chosenDate} />
      </div>
    </div>
  );
}

/* -------------------- Selector bar (Country + City) -------------------- */

function SelectorBar({
  products,
  country,
  onCountry,
  city,
  onCity,
  date,
  onDate,
}: {
  products: DashboardStat[];
  country: string | null;
  onCountry: (c: string | null) => void;
  city: string | null;
  onCity: (c: string | null) => void;
  date: string;
  onDate: (d: string) => void;
}) {
  const countryOptions = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of products) {
      const c = p.product.country || "(unknown)";
      m.set(c, (m.get(c) ?? 0) + 1);
    }
    return [...m.entries()]
      .map(([label, count]) => ({ label, count, hint: flagFor(label) }))
      .sort((a, b) => b.count - a.count);
  }, [products]);

  const cityOptions = useMemo(() => {
    if (!country) return [];
    const m = new Map<string, number>();
    for (const p of products) {
      if (p.product.country !== country) continue;
      const c = p.product.city || "(unknown)";
      m.set(c, (m.get(c) ?? 0) + 1);
    }
    return [...m.entries()]
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count);
  }, [products, country]);

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <SelectPill
        icon={<Globe className="w-3.5 h-3.5" />}
        placeholder="Choose country"
        value={country}
        valuePrefix={country ? flagFor(country) : undefined}
        options={countryOptions}
        onSelect={onCountry}
        searchPlaceholder="Search country…"
      />
      <ChevronRight className="w-3.5 h-3.5 text-[#C7CACF]" />
      <SelectPill
        icon={<MapPin className="w-3.5 h-3.5" />}
        placeholder={country ? "Choose city" : "Pick country first"}
        value={city}
        options={cityOptions}
        onSelect={onCity}
        searchPlaceholder="Search city…"
        disabled={!country}
      />
      <ChevronRight className="w-3.5 h-3.5 text-[#C7CACF]" />
      <DatePill value={date} onChange={onDate} />
    </div>
  );
}

/* -------------------- Date pill -------------------- */

function DatePill({
  value,
  onChange,
}: {
  value: string;
  onChange: (d: string) => void;
}) {
  // window: today .. today + 60 days
  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const max = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() + 60);
    return d.toISOString().slice(0, 10);
  }, []);
  const displayVal = new Date(value + "T00:00:00").toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  const isToday = value === today;
  const inputRef = useRef<HTMLInputElement>(null);

  function openPicker() {
    // Chrome only opens the native date-picker via user-gesture-invoked
    // showPicker() — the invisible-overlay + label trick isn't reliable.
    const el = inputRef.current;
    if (!el) return;
    // Fall back to focus() if showPicker() is unavailable.
    if (typeof el.showPicker === "function") el.showPicker();
    else el.focus();
  }

  return (
    <button
      type="button"
      onClick={openPicker}
      className="relative inline-flex items-center gap-2 px-3.5 py-2 rounded-[10px] text-[13px] font-semibold border border-[#9FD4CE] bg-[#F2FAF9] text-[#0E6F6A] hover:bg-white transition-all cursor-pointer"
    >
      <Calendar className="w-3.5 h-3.5" />
      <span>{isToday ? `${displayVal} (today)` : displayVal}</span>
      <ChevronDown className="w-3 h-3 opacity-70" />
      <input
        ref={inputRef}
        type="date"
        min={today}
        max={max}
        value={value}
        onChange={(e) => {
          if (e.target.value) onChange(e.target.value);
        }}
        // The input itself is a tiny, off-screen anchor for the picker so
        // Chrome positions the calendar under the chip. Visually hidden.
        className="absolute inset-0 opacity-0 pointer-events-none"
      />
    </button>
  );
}

interface SelectOption {
  label: string;
  count?: number;
  hint?: string;
}

function SelectPill({
  icon,
  placeholder,
  value,
  valuePrefix,
  options,
  onSelect,
  searchPlaceholder,
  disabled,
}: {
  icon: React.ReactNode;
  placeholder: string;
  value: string | null;
  valuePrefix?: string;
  options: SelectOption[];
  onSelect: (v: string | null) => void;
  searchPlaceholder: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const isEmpty = !value;

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-[10px] text-[13px] font-semibold border transition-all ${
          disabled
            ? "bg-[#F6F7F9] text-[#B0B4BB] border-[#E7E8EB] cursor-not-allowed"
            : isEmpty
              ? "bg-white border-[#E2E3E7] text-[#5C6069] hover:border-[#9FD4CE] hover:text-[#0E6F6A]"
              : "bg-[#F2FAF9] border-[#9FD4CE] text-[#0E6F6A] hover:bg-white"
        }`}
      >
        <span className={disabled ? "text-[#C7CACF]" : "text-[#9AA0A8]"}>{icon}</span>
        {valuePrefix && <span className="text-[15px] leading-none">{valuePrefix}</span>}
        <span className={isEmpty ? "font-medium" : ""}>{value ?? placeholder}</span>
        {value && !disabled && (
          <span
            role="button"
            onClick={(e) => {
              e.stopPropagation();
              onSelect(null);
            }}
            className="text-[#9AA0A8] hover:text-[#B5342C] ml-0.5"
            title="Clear"
          >
            <X className="w-3 h-3" />
          </span>
        )}
        {!value && (
          <ChevronDown
            className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`}
          />
        )}
      </button>
      {open && !disabled && (
        <PillPopover
          anchorRef={btnRef}
          options={options}
          selected={value}
          onSelect={(v) => {
            onSelect(v);
            setOpen(false);
          }}
          onClose={() => setOpen(false)}
          searchPlaceholder={searchPlaceholder}
        />
      )}
    </>
  );
}

function PillPopover({
  anchorRef,
  options,
  selected,
  onSelect,
  onClose,
  searchPlaceholder,
}: {
  anchorRef: React.RefObject<HTMLButtonElement | null>;
  options: SelectOption[];
  selected: string | null;
  onSelect: (v: string) => void;
  onClose: () => void;
  searchPlaceholder: string;
}) {
  const popRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const [mounted, setMounted] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!anchorRef.current) return;
    const rect = anchorRef.current.getBoundingClientRect();
    setPos({ top: rect.bottom + 6, left: rect.left });
    setMounted(true);
  }, [anchorRef]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      const t = e.target as Node;
      if (popRef.current?.contains(t)) return;
      if (anchorRef.current?.contains(t)) return;
      onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose, anchorRef]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.label.toLowerCase().includes(q));
  }, [options, query]);

  if (!mounted || !pos) return null;

  return createPortal(
    <div
      ref={popRef}
      style={{ position: "fixed", top: pos.top, left: pos.left, width: 320, zIndex: 60 }}
      className="rounded-[12px] border border-[#EBECEF] bg-white shadow-xl ring-1 ring-black/5"
    >
      <div className="p-2 border-b border-[#F1F2F4]">
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-[#9AA0A8]" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={searchPlaceholder}
            className="w-full pl-8 pr-2.5 py-1.5 rounded-[7px] border border-[#E2E3E7] text-[12.5px] focus:outline-none focus:border-[#0E6F6A]"
          />
        </div>
      </div>
      <ul className="max-h-72 overflow-y-auto">
        {filtered.map((o) => {
          const isSel = o.label === selected;
          return (
            <li key={o.label}>
              <button
                type="button"
                onClick={() => onSelect(o.label)}
                className={`w-full text-left px-3.5 py-2 flex items-center gap-2 text-[13px] transition-colors ${
                  isSel
                    ? "bg-[#F2FAF9] text-[#0E6F6A] font-semibold"
                    : "text-[#1F2127] hover:bg-[#FAFBFC]"
                }`}
              >
                {o.hint && <span className="text-[15px] leading-none">{o.hint}</span>}
                <span className="flex-1 truncate">{o.label}</span>
                {o.count != null && (
                  <span className="tnum text-[11px] text-[#9AA0A8]">{o.count}</span>
                )}
                {isSel && <Check className="w-3.5 h-3.5" strokeWidth={3} />}
              </button>
            </li>
          );
        })}
        {filtered.length === 0 && (
          <li className="px-3.5 py-4 text-[12px] text-[#9AA0A8] text-center">
            No matches for &ldquo;{query}&rdquo;
          </li>
        )}
      </ul>
    </div>,
    document.body,
  );
}

/* -------------------- Products panel (left column) -------------------- */

function ProductPanel({
  products,
  country,
  city,
  chosenProductId,
  onPick,
}: {
  products: DashboardStat[];
  country: string | null;
  city: string | null;
  chosenProductId: number | null;
  onPick: (p: DashboardStat) => void;
}) {
  const [query, setQuery] = useState("");

  const inScope = useMemo(() => {
    if (!country || !city) return [];
    return products.filter(
      (p) => p.product.country === country && p.product.city === city,
    );
  }, [products, country, city]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return inScope;
    return inScope.filter((p) =>
      `${p.product.name} ${p.product.type ?? ""} #${p.product.id}`
        .toLowerCase()
        .includes(q),
    );
  }, [inScope, query]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      if ((a.option_count > 0) !== (b.option_count > 0)) {
        return a.option_count > 0 ? -1 : 1;
      }
      return b.option_count - a.option_count;
    });
  }, [filtered]);

  const withOpts = inScope.filter((p) => p.option_count > 0).length;

  return (
    <PanelShell
      title="Products"
      count={inScope.length}
      subtitle={
        country && city
          ? `${withOpts} of ${inScope.length} with options`
          : undefined
      }
    >
      {!country || !city ? (
        <PanelHint>Pick a country & city above.</PanelHint>
      ) : inScope.length === 0 ? (
        <PanelHint>No products in {city}.</PanelHint>
      ) : (
        <>
          <ListSearch
            value={query}
            onChange={setQuery}
            placeholder="Search product name, type…"
          />
          <ul className="flex-1 overflow-y-auto -mx-1 mt-1">
            {sorted.map((p) => (
              <ProductRow
                key={p.product.id}
                product={p}
                selected={chosenProductId === p.product.id}
                onClick={() => onPick(p)}
              />
            ))}
            {sorted.length === 0 && (
              <PanelHint>No products match &ldquo;{query}&rdquo;.</PanelHint>
            )}
          </ul>
        </>
      )}
    </PanelShell>
  );
}

function ProductRow({
  product,
  selected,
  onClick,
}: {
  product: DashboardStat;
  selected: boolean;
  onClick: () => void;
}) {
  const { product: p, option_count, seller_count, rayna_price } = product;
  const hasOptions = option_count > 0;
  const min = rayna_price.min_price;
  const max = rayna_price.max_price;
  const priceLine =
    min != null && max != null
      ? min === max
        ? fmtMoney(min, rayna_price.currency)
        : `${fmtMoney(min, rayna_price.currency)} – ${fmtMoney(max, rayna_price.currency)}`
      : null;

  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        disabled={!hasOptions}
        className={`w-full text-left px-3 py-2.5 rounded-[9px] transition-colors flex items-start gap-2.5 ${
          selected
            ? "bg-[#0E6F6A] text-white shadow-sm"
            : hasOptions
              ? "hover:bg-[#F2FAF9] text-[#1F2127]"
              : "text-[#9AA0A8] opacity-70 cursor-not-allowed"
        }`}
      >
        <span
          className={`w-[26px] h-[26px] shrink-0 rounded-[7px] grid place-items-center text-[15px] leading-none mt-0.5 ${
            selected
              ? "bg-white/20"
              : "bg-[#F2FAF9] border border-[#DCEFEC]"
          }`}
        >
          {emojiForProduct(p.name)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-1.5 mb-0.5">
            <span
              className={`text-[9px] font-mono uppercase tracking-[0.06em] ${
                selected ? "text-white/70" : "text-[#9AA0A8]"
              }`}
            >
              #{p.id}
            </span>
            {p.type && (
              <span
                className={`text-[9px] font-mono uppercase tracking-[0.05em] ${
                  selected ? "text-white/60" : "text-[#B0B4BB]"
                }`}
              >
                {p.type}
              </span>
            )}
          </div>
          <div className="text-[12.5px] font-medium leading-snug line-clamp-2">
            {p.name}
          </div>
          <div
            className={`text-[10.5px] mt-1 flex items-center gap-1.5 ${
              selected ? "text-white/75" : "text-[#8A8F98]"
            }`}
          >
            <span className="tnum font-semibold">
              {option_count} opt{option_count === 1 ? "" : "s"}
            </span>
            <span className={selected ? "text-white/40" : "text-[#D5D7DC]"}>·</span>
            <span className="tnum">{seller_count} sellers</span>
            {priceLine && (
              <>
                <span className={selected ? "text-white/40" : "text-[#D5D7DC]"}>·</span>
                <span className="tnum truncate">{priceLine}</span>
              </>
            )}
          </div>
        </div>
      </button>
    </li>
  );
}

/* -------------------- Options panel (middle column) -------------------- */

function OptionPanel({
  country,
  city,
  product,
  chosenOptionId,
  onPick,
  autoSelectOptionId,
}: {
  country: string | null;
  city: string | null;
  product: DashboardStat | null;
  chosenOptionId: number | null;
  onPick: (o: OptionListItem) => void;
  autoSelectOptionId?: number | null;
}) {
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<OptionListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Only auto-select on first successful load; if the user then manually
  // clears their choice, don't force-reselect from the URL param.
  const autoSelectedRef = useRef(false);

  const productId = product?.product.id ?? null;

  useEffect(() => {
    if (!country || !city || productId == null) {
      setOptions(null);
      return;
    }
    let cancelled = false;
    setOptions(null);
    setError(null);
    const qs = new URLSearchParams({ country, city }).toString();
    fetch(`${API_BASE_PUBLIC}/api/options/by-location?${qs}`, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`API ${r.status}`);
        return r.json();
      })
      .then((data: OptionListItem[]) => {
        if (cancelled) return;
        const scoped = data.filter((o) => o.product_id === productId);
        setOptions(scoped);
        if (
          autoSelectOptionId != null &&
          !autoSelectedRef.current &&
          chosenOptionId == null
        ) {
          const match = scoped.find((o) => o.option_id === autoSelectOptionId);
          if (match) {
            autoSelectedRef.current = true;
            onPick(match);
          }
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [country, city, productId, autoSelectOptionId, chosenOptionId, onPick]);

  const filtered = useMemo(() => {
    if (!options) return [];
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) =>
      `${o.name} #${o.option_id}`.toLowerCase().includes(q),
    );
  }, [options, query]);

  return (
    <PanelShell
      title="Options"
      count={options?.length ?? undefined}
      subtitle={
        product ? `for ${truncate(product.product.name, 32)}` : undefined
      }
    >
      {!product ? (
        <PanelHint>Pick a product to see its bookable options.</PanelHint>
      ) : error ? (
        <div className="rounded-[10px] border border-[#F1C7C2] bg-[#FBEAE8] px-3 py-2.5 text-[12px] text-[#B5342C] mt-1">
          {error}
        </div>
      ) : options == null ? (
        <PanelHint>
          <Loader2 className="w-3.5 h-3.5 animate-spin inline-block mr-1.5 align-[-2px]" />
          Loading options…
        </PanelHint>
      ) : options.length === 0 ? (
        <PanelHint>
          Vercel feed didn&rsquo;t return any variants for this product (likely a
          holiday/cruise/yacht/visa — the feed only lists options for activities).
        </PanelHint>
      ) : (
        <>
          <ListSearch
            value={query}
            onChange={setQuery}
            placeholder="Search variant, transfer type…"
          />
          <ul className="flex-1 overflow-y-auto -mx-1 mt-1">
            {filtered.map((o) => (
              <OptionRow
                key={o.option_id}
                option={o}
                selected={chosenOptionId === o.option_id}
                onClick={() => onPick(o)}
              />
            ))}
            {filtered.length === 0 && (
              <PanelHint>No options match &ldquo;{query}&rdquo;.</PanelHint>
            )}
          </ul>
        </>
      )}
    </PanelShell>
  );
}

function OptionRow({
  option,
  selected,
  onClick,
}: {
  option: OptionListItem;
  selected: boolean;
  onClick: () => void;
}) {
  // If the option name starts with the parent product name, strip that prefix
  // so the row emphasises the variant (transfer type / tier).
  let tierLine = option.name;
  const prefix = option.product_name + " – ";
  if (tierLine.toLowerCase().startsWith(prefix.toLowerCase())) {
    tierLine = tierLine.slice(prefix.length);
  } else if (tierLine.toLowerCase().startsWith(option.product_name.toLowerCase())) {
    tierLine = tierLine.slice(option.product_name.length).replace(/^[\s\-–—:·]+/, "");
  }
  if (!tierLine.trim()) tierLine = "Standard";

  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className={`w-full text-left px-3 py-2.5 rounded-[9px] transition-colors ${
          selected
            ? "bg-[#0E6F6A] text-white shadow-sm"
            : "hover:bg-[#F2FAF9] text-[#1F2127]"
        }`}
      >
        <div className="flex items-start justify-between gap-2 mb-1">
          <div
            className={`text-[9px] font-mono uppercase tracking-[0.06em] ${
              selected ? "text-white/70" : "text-[#9AA0A8]"
            }`}
          >
            variant #{option.option_id.toString().slice(-5)}
          </div>
          {option.mapped_count > 0 && (
            <span
              className={`inline-flex items-center gap-1 text-[9.5px] font-bold uppercase tracking-[0.04em] ${
                selected ? "text-white" : "text-[#197A45]"
              }`}
            >
              <Check className="w-2.5 h-2.5" strokeWidth={3} />
              {option.mapped_count}
            </span>
          )}
        </div>
        <div className="text-[12.5px] font-medium leading-snug line-clamp-2">
          {tierLine}
        </div>
        <div className="flex items-baseline gap-2 mt-1.5">
          <span
            className={`tnum text-[14px] font-semibold ${
              selected ? "text-white" : "text-[#16181D]"
            }`}
          >
            {option.price != null
              ? fmtMoney(option.price, option.currency)
              : "—"}
          </span>
          <span
            className={`text-[10.5px] font-mono ${
              selected ? "text-white/70" : "text-[#8A8F98]"
            }`}
          >
            {fmtBasis(option.pricing_basis)}
          </span>
          <span
            className={`ml-auto text-[10.5px] ${
              selected ? "text-white/70" : "text-[#8A8F98]"
            }`}
          >
            <span className="tnum font-semibold">{option.seller_count}</span>{" "}
            sellers
          </span>
        </div>
      </button>
    </li>
  );
}

/* -------------------- Panel shell + helpers -------------------- */

function PanelShell({
  title,
  count,
  subtitle,
  children,
}: {
  title: string;
  count?: number;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white border border-[#EBECEF] rounded-[13px] flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-[#F1F2F4] flex items-baseline gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-[0.09em] text-[#5C6069]">
          {title}
        </span>
        {count != null && (
          <span className="tnum text-[11px] text-[#9AA0A8]">
            {count}
          </span>
        )}
        {subtitle && (
          <span className="text-[11px] text-[#9AA0A8] truncate ml-1">
            {subtitle}
          </span>
        )}
      </div>
      <div className="flex flex-col flex-1 min-h-0 p-2">{children}</div>
    </div>
  );
}

function PanelHint({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[12px] text-[#8A8F98] px-3 py-6 text-center flex-1 flex items-center justify-center">
      <span>{children}</span>
    </div>
  );
}

function ListSearch({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <div className="relative px-1">
      <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-[#9AA0A8] pointer-events-none" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full pl-8 pr-8 py-1.5 rounded-[8px] border border-[#E2E3E7] bg-white text-[12.5px] text-[#1F2127] placeholder:text-[#9AA0A8] focus:outline-none focus:border-[#0E6F6A]"
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-[#9AA0A8] hover:text-[#5C6069] p-0.5"
          title="Clear"
        >
          <X className="w-3 h-3" />
        </button>
      )}
    </div>
  );
}

function EmptyHint({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-[14px] border border-dashed border-[#D5D7DC] bg-white px-8 py-12 text-center text-[13px] text-[#8A8F98] mt-4">
      {children}
    </div>
  );
}

/* -------------------- Right pane: competitors -------------------- */

function RightPane({
  chosenOption,
  chosenDate,
}: {
  chosenOption: OptionListItem | null;
  chosenDate: string;
}) {
  return (
    <div className="bg-white border border-[#EBECEF] rounded-[13px] overflow-y-auto min-h-0">
      {chosenOption ? (
        <ComparePanel chosenOption={chosenOption} chosenDate={chosenDate} />
      ) : (
        <div className="h-full flex items-center justify-center px-10 py-16 text-center">
          <div>
            <div className="w-[52px] h-[52px] rounded-[14px] bg-[#F2FAF9] border border-[#DCEFEC] grid place-items-center mx-auto mb-4 text-[24px]">
              🎯
            </div>
            <div className="text-[15px] font-semibold text-[#1F2127] mb-1.5">
              Pick an option to see competitors
            </div>
            <p className="text-[12.5px] text-[#8A8F98] max-w-[320px] leading-relaxed">
              Choose a country, city, product, and one bookable option on the
              left. The comparable competitor prices will show up right here.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

/* -------------------- Compare panel (right side content) -------------------- */

function ComparePanel({
  chosenOption,
  chosenDate,
}: {
  chosenOption: OptionListItem;
  chosenDate: string;
}) {
  const productId = chosenOption.product_id;
  const toast = useToast();
  const [workspace, setWorkspace] = useState<ProductMappingPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  // build the workspace URL with the chosen date so the backend swaps in
  // per-date observations from price_observations.
  const workspaceUrl = useMemo(
    () =>
      `${API_BASE_PUBLIC}/api/products/${productId}/mapping-workspace?date=${encodeURIComponent(chosenDate)}`,
    [productId, chosenDate],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(workspaceUrl, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`API ${r.status}`);
        return r.json();
      })
      .then((data: ProductMappingPayload) => {
        if (!cancelled) setWorkspace(data);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceUrl]);

  function refresh() {
    startTransition(() => {
      fetch(workspaceUrl, { cache: "no-store" })
        .then((r) => r.json())
        .then((data: ProductMappingPayload) => setWorkspace(data))
        .catch(console.error);
    });
  }

  async function mapOption(competitorOptionId: number, raynaOptionId: number) {
    const r = await fetch(`${API_BASE_PUBLIC}/api/mappings/manual`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rayna_option_id: raynaOptionId,
        competitor_option_id: competitorOptionId,
      }),
    });
    if (!r.ok) {
      let detail = `Mapping failed (${r.status})`;
      try {
        const body = await r.json();
        if (body && typeof body.detail === "string") detail = body.detail;
      } catch {
        /* not JSON */
      }
      toast.error(detail);
      return;
    }
    toast.success("Mapped");
    refresh();
  }

  async function unmap(mappingId: number) {
    const r = await fetch(`${API_BASE_PUBLIC}/api/mappings/${mappingId}`, {
      method: "DELETE",
    });
    if (!r.ok && r.status !== 204) {
      toast.error(`Unmap failed (${r.status})`);
      return;
    }
    toast.success("Unmapped");
    refresh();
  }

  return (
    <div className="p-5">
      {loading && !workspace ? (
        <div className="flex items-center gap-2 text-[#8A8F98] px-2 py-12 text-[13px]">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading competitors…
        </div>
      ) : error ? (
        <div className="rounded-[12px] border border-[#F1C7C2] bg-[#FBEAE8] px-5 py-4 text-[13px] text-[#B5342C]">
          {error}
        </div>
      ) : workspace ? (
        <WorkspacePanel
          workspace={workspace}
          focusOptionId={chosenOption.option_id}
          chosenDate={chosenDate}
          onMap={mapOption}
          onUnmap={unmap}
          onRefresh={refresh}
        />
      ) : null}
    </div>
  );
}

/* ==============================================================
   Below: reused competitors sub-components (unchanged from the
   wizard version).
   ============================================================== */

function WorkspacePanel({
  workspace,
  focusOptionId,
  chosenDate,
  onMap,
  onUnmap,
  onRefresh,
}: {
  workspace: ProductMappingPayload;
  focusOptionId?: number;
  chosenDate: string;
  onMap: (compId: number, raynaId: number) => Promise<void>;
  onUnmap: (mappingId: number) => Promise<void>;
  onRefresh: () => void;
}) {
  const { product, rayna_options, sellers, total_competitor_options } = workspace;

  const visibleOptions = focusOptionId
    ? rayna_options.filter((o) => o.id === focusOptionId)
    : rayna_options;

  const mappedCount = sellers.reduce(
    (acc, s) =>
      acc +
      s.options.filter(
        (o) =>
          o.mapping != null &&
          (!focusOptionId || o.mapping.rayna_option_id === focusOptionId),
      ).length,
    0,
  );

  const [selectedRaynaId, setSelectedRaynaId] = useState<number | null>(
    focusOptionId ?? rayna_options[0]?.id ?? null,
  );
  const [urlModalOpen, setUrlModalOpen] = useState(false);

  useEffect(() => {
    setSelectedRaynaId(focusOptionId ?? rayna_options[0]?.id ?? null);
  }, [product.id, rayna_options, focusOptionId]);

  const selectedRaynaOption = rayna_options.find((o) => o.id === selectedRaynaId) ?? null;

  const countByRaynaOption = new Map<number, number>();
  for (const seller of sellers) {
    for (const opt of seller.options) {
      if (opt.mapping) {
        const k = opt.mapping.rayna_option_id;
        countByRaynaOption.set(k, (countByRaynaOption.get(k) ?? 0) + 1);
      }
    }
  }

  return (
    <div>
      <div className="flex items-start justify-between mb-2 gap-4">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.09em] text-[#5C6069] mb-1.5">
            Comparing
          </div>
          <h2 className="text-[20px] font-semibold text-[#1F2127] -tracking-[0.02em] leading-tight">
            {product.name}
          </h2>
          <div className="text-[12.5px] text-[#8A8F98] mt-1">
            {product.city}, {product.country} · {product.currency}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10.5px] uppercase tracking-[0.06em] text-[#9AA0A8] font-semibold">
            Mapped
          </div>
          <div className="tnum text-[22px] font-semibold text-[#16181D] mt-0.5">
            {mappedCount}
            <span className="text-[#D5D7DC] mx-1">/</span>
            <span className="text-[#9AA0A8]">{total_competitor_options}</span>
          </div>
        </div>
      </div>

      {visibleOptions.length === 0 ? (
        <EmptyHint>This option could not be loaded.</EmptyHint>
      ) : (
        <>
          <div className="mt-5 mb-6">
            <div className="flex items-center gap-3 mb-3">
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.09em] text-[#5C6069]">
                {focusOptionId
                  ? "Your option (map target)"
                  : `Your options (${rayna_options.length})`}
              </h3>
              <div className="flex-1 h-px bg-[#EBECEF]" />
            </div>
            <div className="grid grid-cols-1 gap-3">
              {visibleOptions.map((ro) => (
                <RaynaOptionCard
                  key={ro.id}
                  option={ro}
                  selected={selectedRaynaId === ro.id}
                  mappedCount={countByRaynaOption.get(ro.id) ?? 0}
                  onSelect={
                    focusOptionId ? () => {} : () => setSelectedRaynaId(ro.id)
                  }
                />
              ))}
            </div>
          </div>

          <div>
            <div className="flex items-center gap-3 mb-3">
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.09em] text-[#5C6069]">
                Competitors
              </h3>
              <div className="flex-1 h-px bg-[#EBECEF]" />
              {sellers.length > 0 && (
                <span className="text-[11px] text-[#9AA0A8]">
                  {sellers.length} sellers · {total_competitor_options} options
                </span>
              )}
              <button
                type="button"
                onClick={() => setUrlModalOpen(true)}
                disabled={selectedRaynaId == null}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[7px] text-[11.5px] font-semibold bg-white text-[#0E6F6A] border border-[#9FD4CE] hover:bg-[#F2FAF9] hover:border-[#0E6F6A] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                title={
                  selectedRaynaId == null
                    ? "Select a Rayna option first"
                    : "Paste a competitor URL to fetch, compare and map"
                }
              >
                <LinkIcon className="w-3 h-3" strokeWidth={2.5} />
                Add by URL
              </button>
            </div>
            {sellers.length === 0 ? (
              <EmptyHint>
                No apple-to-apple competitor on Headout/GlobalTix for this
                product yet. Use <strong>Add by URL</strong> above to paste a
                Viator / GetYourGuide / local seller link.
              </EmptyHint>
            ) : (
              <div className="space-y-3">
                {sellers.map((seller) => (
                  <SellerCard
                    key={seller.seller_domain}
                    sellerDomain={seller.seller_domain}
                    listingCount={seller.listing_count}
                    options={seller.options}
                    raynaOptions={rayna_options}
                    selectedRaynaId={selectedRaynaId}
                    productId={product.id}
                    chosenDate={chosenDate}
                    onMap={onMap}
                    onUnmap={onUnmap}
                  />
                ))}
              </div>
            )}
          </div>
        </>
      )}
      {urlModalOpen && (
        <AddCompetitorByUrlModal
          raynaOptionId={selectedRaynaId}
          raynaOptionName={selectedRaynaOption?.name ?? null}
          onClose={() => setUrlModalOpen(false)}
          onSaved={() => onRefresh()}
        />
      )}
    </div>
  );
}

function RaynaOptionCard({
  option,
  selected,
  mappedCount,
  onSelect,
}: {
  option: RaynaOption;
  selected: boolean;
  mappedCount: number;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`text-left rounded-[12px] p-4 transition-all ${
        selected
          ? "bg-[#F2FAF9] border-[1.5px] border-[#9FD4CE] shadow-sm ring-2 ring-[#DCEFEC]"
          : "bg-white border border-[#EBECEF] hover:border-[#D5D7DC] hover:shadow-sm"
      }`}
    >
      <div className="flex items-center justify-between mb-2.5">
        <div
          className={`text-[10px] font-mono tracking-[0.06em] uppercase ${
            selected ? "text-[#0E6F6A]" : "text-[#9AA0A8]"
          }`}
        >
          Option #{option.id}
        </div>
        {selected && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-[5px] text-[9px] font-bold uppercase tracking-[0.05em] bg-[#0E6F6A] text-white">
            <Check className="w-2.5 h-2.5" strokeWidth={3} />
            Target
          </span>
        )}
      </div>
      <div
        className={`text-[13px] font-medium leading-snug mb-3.5 min-h-[2.4rem] ${
          selected ? "text-[#0E6F6A]" : "text-[#1F2127]"
        }`}
      >
        {option.name}
      </div>
      <div className="flex items-baseline justify-between gap-2 mb-1.5">
        <span className="tnum text-[18px] font-semibold text-[#16181D]">
          {fmtMoney(option.price, option.currency)}
        </span>
        <span className="text-[10.5px] text-[#8A8F98] font-mono">
          {fmtBasis(option.pricing_basis)}
        </span>
      </div>
      {mappedCount > 0 && (
        <div className="text-[11px] text-[#197A45] font-semibold mt-2 flex items-center gap-1">
          <Check className="w-3 h-3" strokeWidth={3} />
          {mappedCount} competitor{mappedCount === 1 ? "" : "s"} mapped
        </div>
      )}
    </button>
  );
}

function SellerCard({
  sellerDomain,
  listingCount,
  options,
  raynaOptions,
  selectedRaynaId,
  productId,
  chosenDate,
  onMap,
  onUnmap,
}: {
  sellerDomain: string;
  listingCount: number;
  options: CompetitorOptionForMapping[];
  raynaOptions: RaynaOption[];
  selectedRaynaId: number | null;
  productId: number;
  chosenDate: string;
  onMap: (compId: number, raynaId: number) => Promise<void>;
  onUnmap: (mappingId: number) => Promise<void>;
}) {
  const mapped = options.filter((o) => o.mapping != null).length;
  return (
    <div>
      <div className="flex items-center gap-2.5 px-1 py-2">
        <span className="w-[22px] h-[22px] rounded-[6px] bg-[#F2F3F5] border border-[#EAEBEE] grid place-items-center text-[11px] font-bold text-[#6B7280]">
          {sellerDomain[0].toUpperCase()}
        </span>
        <span className="font-mono text-[12.5px] font-semibold text-[#3D424B]">
          {sellerDomain}
        </span>
        <span className="text-[11px] text-[#9AA0A8]">
          · {options.length} option{options.length === 1 ? "" : "s"}
          {listingCount > 1 ? ` · ${listingCount} pages` : ""}
        </span>
        {mapped > 0 && (
          <span className="ml-auto inline-flex items-center gap-1 px-2 py-[3px] rounded-[6px] text-[10.5px] font-semibold bg-[#E8F5EC] text-[#197A45] border border-[#BFE3CB]">
            <Check className="w-2.5 h-2.5" strokeWidth={3} />
            {mapped} mapped
          </span>
        )}
      </div>
      <ul className="rounded-[10px] border border-[#EBECEF] bg-white divide-y divide-[#F1F2F4] overflow-hidden">
        {options.map((opt) => (
          <CompetitorRow
            key={opt.option_id}
            option={opt}
            raynaOptions={raynaOptions}
            selectedRaynaId={selectedRaynaId}
            productId={productId}
            chosenDate={chosenDate}
            onMap={onMap}
            onUnmap={onUnmap}
          />
        ))}
      </ul>
    </div>
  );
}

function CompetitorRow({
  option,
  raynaOptions,
  selectedRaynaId,
  productId,
  chosenDate,
  onMap,
  onUnmap,
}: {
  option: CompetitorOptionForMapping;
  raynaOptions: RaynaOption[];
  selectedRaynaId: number | null;
  productId: number;
  chosenDate: string;
  onMap: (compId: number, raynaId: number) => Promise<void>;
  onUnmap: (mappingId: number) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  async function handleMap(raynaId: number) {
    setBusy(true);
    setOpen(false);
    try {
      await onMap(option.option_id, raynaId);
    } finally {
      setBusy(false);
    }
  }

  async function handleUnmap() {
    if (!option.mapping) return;
    setBusy(true);
    try {
      await onUnmap(option.mapping.mapping_id);
    } finally {
      setBusy(false);
    }
  }

  const mapped = option.mapping != null;
  const directRaynaId =
    selectedRaynaId ?? (raynaOptions.length === 1 ? raynaOptions[0]!.id : null);
  const directMode = directRaynaId != null;
  const showPopover = !mapped && !directMode;
  const compareRaynaId =
    directRaynaId ?? option.mapping?.rayna_option_id ?? raynaOptions[0]?.id ?? null;
  const compareUrl =
    compareRaynaId != null
      ? `/compare?productId=${productId}&raynaOptionId=${compareRaynaId}&competitorOptionId=${option.option_id}&date=${encodeURIComponent(chosenDate)}`
      : null;

  const mappedName = option.mapping?.rayna_option_name ?? "";
  const mappedNameShort =
    mappedName.length > 36 ? mappedName.slice(0, 34) + "…" : mappedName;
  return (
    <li
      className={`relative pl-4 pr-3 py-3 transition-colors ${
        mapped
          ? "bg-[#F2FAF9] hover:bg-[#E8F5EC]/40"
          : "hover:bg-[#FAFBFC]/60"
      }`}
    >
      {mapped && (
        <span
          aria-hidden
          className="absolute left-0 top-0 bottom-0 w-[3px] bg-[#0E6F6A]"
        />
      )}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="min-w-0 flex-1">
          <a
            href={option.listing_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[#1F2127] font-medium text-[13px] hover:text-[#0E6F6A] inline-flex items-start gap-1.5 leading-snug"
          >
            <span className="line-clamp-2">{option.name}</span>
            <ExternalLink className="w-3 h-3 opacity-40 shrink-0 mt-0.5" />
          </a>
          <div className="flex items-center gap-1.5 text-[11px] text-[#8A8F98] mt-1 flex-wrap">
            <span className="tnum font-semibold text-[#1F2127]">
              {fmtAED(option.price, option.currency)}
            </span>
            {option.price != null &&
              (option.currency || "AED").toUpperCase() !== "AED" && (
                <span className="tnum text-[10.5px] text-[#9AA0A8]">
                  ({fmtMoney(option.price, option.currency)})
                </span>
              )}
            <span className="text-[#D5D7DC]">·</span>
            <span className="font-mono">{fmtBasis(option.pricing_basis)}</span>
            {option.tier && option.tier !== "standard" && (
              <>
                <span className="text-[#D5D7DC]">·</span>
                <span className="font-mono text-[#5C6069]">{option.tier}</span>
              </>
            )}
            {mapped && (
              <>
                <span className="text-[#D5D7DC]">·</span>
                <span className="inline-flex items-center gap-1 text-[10.5px] text-[#197A45] font-semibold">
                  <Check className="w-2.5 h-2.5" strokeWidth={3} />
                  → {mappedNameShort}
                </span>
              </>
            )}
          </div>
        </div>

        <div className="shrink-0 flex items-center gap-1.5">
          {compareUrl && (
            <a
              href={compareUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-[7px] text-[11px] font-semibold bg-white text-[#0E6F6A] border border-[#DCEFEC] hover:bg-[#F2FAF9] hover:border-[#0E6F6A] transition-colors"
              title="Open side-by-side comparison in a new tab"
            >
              <ArrowLeftRight className="w-3 h-3" strokeWidth={2.5} />
              Compare
            </a>
          )}
          {mapped ? (
            <button
              type="button"
              disabled={busy}
              onClick={handleUnmap}
              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-[7px] text-[11px] font-semibold text-[#9AA0A8] hover:bg-[#FBEAE8] hover:text-[#B5342C] disabled:opacity-40 transition-colors"
              title="Unmap"
            >
              {busy ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <X className="w-3 h-3" strokeWidth={2.5} />
              )}
              Unmap
            </button>
          ) : showPopover ? (
            <button
              ref={buttonRef}
              type="button"
              disabled={busy}
              onClick={() => setOpen((v) => !v)}
              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-[7px] text-[11px] font-semibold bg-[#0E6F6A] text-white hover:bg-[#0B5853] shadow-sm shadow-[#0E6F6A]/20 disabled:opacity-50 transition-colors"
            >
              {busy ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Plus className="w-3 h-3" strokeWidth={3} />
              )}
              Map to…
              <ChevronDown
                className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`}
              />
            </button>
          ) : (
            <button
              type="button"
              disabled={busy || directRaynaId == null}
              onClick={() => directRaynaId != null && handleMap(directRaynaId)}
              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-[7px] text-[11px] font-semibold bg-[#0E6F6A] text-white hover:bg-[#0B5853] shadow-sm shadow-[#0E6F6A]/20 disabled:opacity-50 transition-colors"
            >
              {busy ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Plus className="w-3 h-3" strokeWidth={3} />
              )}
              Map
            </button>
          )}
        </div>
      </div>

      {open && !mapped && (
        <RaynaOptionPopover
          anchorRef={buttonRef}
          raynaOptions={raynaOptions}
          onPick={handleMap}
          onClose={() => setOpen(false)}
        />
      )}
    </li>
  );
}

function RaynaOptionPopover({
  anchorRef,
  raynaOptions,
  onPick,
  onClose,
}: {
  anchorRef: React.RefObject<HTMLButtonElement | null>;
  raynaOptions: RaynaOption[];
  onPick: (raynaId: number) => Promise<void> | void;
  onClose: () => void;
}) {
  const popRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    if (!anchorRef.current) return;
    const POPOVER_WIDTH = 340;
    const MARGIN = 8;
    function place() {
      const rect = anchorRef.current!.getBoundingClientRect();
      const left = Math.max(8, rect.right - POPOVER_WIDTH);
      const top = rect.bottom + MARGIN;
      setPos({ top, left });
    }
    place();
    setMounted(true);
  }, [anchorRef]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      const target = e.target as Node;
      if (popRef.current?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      onClose();
    }
    function onScroll() {
      onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDocClick);
    window.addEventListener("scroll", onScroll, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      window.removeEventListener("scroll", onScroll, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose, anchorRef]);

  if (!mounted || !pos) return null;

  return createPortal(
    <div
      ref={popRef}
      style={{ position: "fixed", top: pos.top, left: pos.left, width: 340, zIndex: 60 }}
      className="rounded-[12px] border border-[#EBECEF] bg-white shadow-xl ring-1 ring-black/5"
    >
      <div className="px-4 py-2.5 border-b border-[#F1F2F4] text-[10px] uppercase tracking-[0.08em] font-semibold text-[#8A8F98]">
        Map to which Rayna option?
      </div>
      <ul className="max-h-72 overflow-y-auto">
        {raynaOptions.map((ro) => (
          <li key={ro.id}>
            <button
              type="button"
              onClick={() => onPick(ro.id)}
              className="w-full text-left px-4 py-3 hover:bg-[#F2FAF9] transition-colors"
            >
              <div className="font-medium text-[#1F2127] text-[13px] leading-snug line-clamp-2 mb-1">
                {ro.name}
              </div>
              <div className="text-[11px] text-[#8A8F98] font-mono">
                {fmtMoney(ro.price, ro.currency)} · {fmtBasis(ro.pricing_basis)}
              </div>
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={onClose}
        className="w-full text-[11px] text-[#8A8F98] hover:text-[#3D424B] py-2.5 border-t border-[#F1F2F4]"
      >
        Cancel
      </button>
    </div>,
    document.body,
  );
}
