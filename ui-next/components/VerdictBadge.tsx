import { Check, X, Equal } from "lucide-react";

const STYLES = {
  identical: {
    label: "identical",
    bg: "#FFF7ED",
    text: "#047857",
    border: "#A7F3D0",
    icon: Check,
  },
  near: {
    label: "near",
    bg: "#FEF3C7",
    text: "#92400E",
    border: "#FCD34D",
    icon: Equal,
  },
  different: {
    label: "different",
    bg: "#FEE2E2",
    text: "#B91C1C",
    border: "#FCA5A5",
    icon: X,
  },
} as const;

export function VerdictBadge({
  verdict,
  confidence,
}: {
  verdict: "identical" | "near" | "different";
  confidence: number;
}) {
  const s = STYLES[verdict];
  const Icon = s.icon;
  const low = confidence < 0.7;
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-[3px] rounded-[7px] text-[11.5px] font-semibold border"
      style={{ background: s.bg, color: s.text, borderColor: s.border }}
    >
      <Icon className="w-3 h-3" strokeWidth={3} />
      {s.label}
      <span className="tnum text-[10px] font-mono opacity-70 ml-0.5">
        {confidence.toFixed(2)}
        {low ? " ◆" : ""}
      </span>
    </span>
  );
}
