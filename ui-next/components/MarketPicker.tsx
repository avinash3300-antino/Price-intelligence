"use client";

import { useMemo, useState } from "react";
import { Check, Search, X } from "lucide-react";
import type { CountryMarket, Scope } from "@/lib/admin";

/**
 * Country/city scope picker.
 *
 * The catalogue spans 86 countries, so scrolling to find one is the slow path.
 * Search matches country *and* city names, because someone assigning "Dubai"
 * should not have to know it is under United Arab Emirates.
 *
 * Selecting a whole country clears its individual city rows — keeping both
 * would read as if the cities were a further restriction, when a country row
 * already covers every city in it, including ones added later.
 */
export function MarketPicker({
  markets,
  selected,
  onChange,
  disabled,
  maxHeight = "320px",
}: {
  markets: CountryMarket[];
  selected: Scope[];
  onChange: (next: Scope[]) => void;
  disabled?: boolean;
  maxHeight?: string;
}) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return markets;
    return markets
      .map((m) => {
        const countryHit = m.country.toLowerCase().includes(q);
        const cities = countryHit
          ? m.cities
          : m.cities.filter((c) => c.city.toLowerCase().includes(q));
        return countryHit || cities.length ? { ...m, cities } : null;
      })
      .filter(Boolean) as CountryMarket[];
  }, [markets, query]);

  const hasCountry = (country: string) =>
    selected.some((s) => s.country === country && s.city === null);
  const hasCity = (country: string, city: string) =>
    selected.some((s) => s.country === country && s.city === city);

  function toggleCountry(country: string) {
    if (hasCountry(country)) {
      onChange(selected.filter((s) => s.country !== country || s.city !== null));
    } else {
      // Drop that country's city rows; the country row supersedes them.
      onChange([
        ...selected.filter((s) => s.country !== country),
        { country, city: null },
      ]);
    }
  }

  function toggleCity(country: string, city: string) {
    if (hasCity(country, city)) {
      onChange(selected.filter((s) => !(s.country === country && s.city === city)));
    } else {
      onChange([...selected, { country, city }]);
    }
  }

  // "All" applies to what is currently visible, so it composes with search:
  // type "United", press All, and you have selected only those.
  const visibleCountries = filtered.map((m) => m.country);
  const allVisibleSelected =
    visibleCountries.length > 0 && visibleCountries.every(hasCountry);

  function selectAllVisible() {
    const others = selected.filter((s) => !visibleCountries.includes(s.country));
    onChange([...others, ...visibleCountries.map((country) => ({ country, city: null }))]);
  }

  function clearVisible() {
    onChange(selected.filter((s) => !visibleCountries.includes(s.country)));
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <div className="relative flex-1">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-[#98A2B3]" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search country or city"
            disabled={disabled}
            className="w-full pl-8 pr-7 py-1.5 text-[12px] bg-white border border-[#D0D5DD] rounded-[8px] outline-none focus:border-[#EA580C] focus:ring-2 focus:ring-[#FFEDD5] transition"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 text-[#98A2B3] hover:text-[#101828]"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        <button
          type="button"
          disabled={disabled || visibleCountries.length === 0}
          onClick={allVisibleSelected ? clearVisible : selectAllVisible}
          className="shrink-0 px-2.5 py-1.5 rounded-[8px] text-[11.5px] font-semibold border border-[#D0D5DD] text-[#344054] hover:border-[#EA580C] hover:text-[#EA580C] transition disabled:opacity-50"
        >
          {allVisibleSelected ? "Clear" : query ? "All matching" : "All"}
        </button>
      </div>

      <div className="flex items-center justify-between mb-1.5 text-[11px] text-[#98A2B3] tnum">
        <span>
          {filtered.length} of {markets.length} countries
        </span>
        <span>
          {selected.length === 0 ? (
            <span className="text-[#B42318] font-semibold">none selected</span>
          ) : (
            `${selected.length} selected`
          )}
        </span>
      </div>

      <div
        className="border border-[#E4E7EC] rounded-[9px] divide-y divide-[#F2F4F7] overflow-y-auto"
        style={{ maxHeight }}
      >
        {filtered.length === 0 && (
          <div className="px-3.5 py-8 text-center text-[12px] text-[#98A2B3]">
            No market matches &ldquo;{query}&rdquo;.
          </div>
        )}
        {filtered.map((m) => {
          const whole = hasCountry(m.country);
          return (
            <div key={m.country} className="px-3.5 py-2.5">
              <label className="flex items-center gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={whole}
                  disabled={disabled}
                  onChange={() => toggleCountry(m.country)}
                  className="accent-[#EA580C] w-3.5 h-3.5"
                />
                <span className="text-[12.5px] font-semibold text-[#101828]">
                  {m.country}
                </span>
                <span className="text-[11px] text-[#98A2B3] tnum ml-auto">
                  {m.products} products
                </span>
              </label>
              {!whole && m.cities.length > 0 && (
                <div className="mt-1.5 ml-6 flex flex-wrap gap-1.5">
                  {m.cities.map((c) => {
                    const on = hasCity(m.country, c.city);
                    return (
                      <button
                        key={c.city}
                        type="button"
                        disabled={disabled}
                        onClick={() => toggleCity(m.country, c.city)}
                        className={`inline-flex items-center gap-1 px-2 py-[3px] rounded-full text-[11px] font-medium border transition disabled:opacity-50 ${
                          on
                            ? "bg-[#FFF4ED] border-[#FED7AA] text-[#C2410C]"
                            : "bg-white border-[#E4E7EC] text-[#667085] hover:border-[#D0D5DD]"
                        }`}
                      >
                        {on && <Check className="w-3 h-3" />}
                        {c.city}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
