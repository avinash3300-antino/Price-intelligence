function fmt(v: unknown): string {
  if (v == null || v === "") return "—";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

const FIELD_ORDER = [
  "venue",
  "activity_category",
  "tier",
  "pricing_basis",
  "duration_minutes",
  "duration_label",
  "transfer_included",
  "transfer_type",
  "meal_included",
  "meal_type",
  "languages",
  "group_min",
  "group_max",
  "cancellation_window_hours",
  "highlights",
  "inclusions",
  "exclusions",
  "notes",
];

const LABELS: Record<string, string> = {
  venue: "Venue",
  activity_category: "Category",
  tier: "Tier",
  pricing_basis: "Pricing basis",
  duration_minutes: "Duration (min)",
  duration_label: "Duration",
  transfer_included: "Transfer",
  transfer_type: "Transfer type",
  meal_included: "Meal",
  meal_type: "Meal type",
  languages: "Languages",
  group_min: "Min pax",
  group_max: "Max pax",
  cancellation_window_hours: "Cancel ≤ (hrs)",
  highlights: "Highlights",
  inclusions: "Inclusions",
  exclusions: "Exclusions",
  notes: "Notes",
};

export function FingerprintDiff({
  rayna,
  competitor,
}: {
  rayna: Record<string, unknown>;
  competitor: Record<string, unknown>;
}) {
  const r = rayna;
  const c = competitor;

  const allKeys = new Set([...Object.keys(r), ...Object.keys(c)]);
  const orderedKeys = [
    ...FIELD_ORDER.filter((k) => allKeys.has(k)),
    ...[...allKeys].filter((k) => !FIELD_ORDER.includes(k)),
  ];

  return (
    <div className="overflow-hidden  border border-[#E4E7EC]">
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="bg-[#F9FAFB] text-[#98A2B3] text-[10.5px] uppercase tracking-[0.05em] font-semibold">
            <th className="text-left px-3 py-2 font-semibold w-1/4">Field</th>
            <th className="text-left px-3 py-2 font-semibold w-3/8">Rayna</th>
            <th className="text-left px-3 py-2 font-semibold w-3/8">Competitor</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#F1F2F4]">
          {orderedKeys.map((k) => {
            const rv = fmt(r[k]);
            const cv = fmt(c[k]);
            const differs = rv !== cv && (rv !== "—" || cv !== "—");
            return (
              <tr key={k} className={differs ? "bg-[#FBF1DE]/30" : ""}>
                <td className="px-3 py-2 text-[#667085] font-medium">
                  {LABELS[k] ?? k}
                </td>
                <td className="px-3 py-2 text-[#344054]">{rv}</td>
                <td
                  className={`px-3 py-2 ${
                    differs ? "text-[#101828] font-semibold" : "text-[#344054]"
                  }`}
                >
                  {cv}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
