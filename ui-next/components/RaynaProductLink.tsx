import { ExternalLink } from "lucide-react";

/**
 * Link out to a product's own page on raynatours.com.
 *
 * Wherever one of our products is named, this sits beside it — the price being
 * compared is only meaningful next to what the customer actually sees, and
 * hunting for the page by hand is the friction that stops people checking.
 *
 * Deliberately one component rather than five hand-rolled anchors: the label,
 * the icon size and the hover treatment stay identical across the mapping
 * workspace, /mapped, the portfolio table, the review queue and both detail
 * pages.
 *
 * Renders nothing without a url. Every catalogue row has one today, but the
 * column is nullable and a future import may not.
 */
export function RaynaProductLink({
  url,
  name,
  size = "sm",
  className = "",
}: {
  url: string | null | undefined;
  name: string;
  /** sm inside dense tables and lists; md beside a page heading. */
  size?: "sm" | "md";
  className?: string;
}) {
  if (!url) return null;
  const px = size === "md" ? "w-4 h-4" : "w-3.5 h-3.5";
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      // Stop the click reaching a clickable row or card underneath: opening
      // the seller page and selecting the row are different intents.
      onClick={(e) => e.stopPropagation()}
      title={`Open ${name} on raynatours.com`}
      aria-label={`Open ${name} on raynatours.com`}
      className={`inline-flex shrink-0 p-0.5 rounded-[5px] text-[#98A2B3] hover:text-[#EA580C] outline-none focus-visible:ring-2 focus-visible:ring-[#FDBA74] transition ${className}`}
    >
      <ExternalLink className={px} />
    </a>
  );
}
