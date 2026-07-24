"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Loader2, Plus, X, AlertTriangle } from "lucide-react";
import { API_BASE_PUBLIC } from "@/lib/api";
import { useToast } from "@/components/Toast";

interface Props {
  productId: number;
  raynaOptionId: number;
  raynaOptionName: string;
  competitorOptionId: number;
  existingMapping: {
    mapping_id: number;
    rayna_option_id: number;
    rayna_option_name: string;
  } | null;
}

export function CompareActionBar({
  productId,
  raynaOptionId,
  raynaOptionName,
  competitorOptionId,
  existingMapping,
}: Props) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const mappedToThis =
    existingMapping != null &&
    existingMapping.rayna_option_id === raynaOptionId;
  const mappedElsewhere =
    existingMapping != null &&
    existingMapping.rayna_option_id !== raynaOptionId;

  // Backend returns errors as `{"detail": "..."}` for HTTPException. Parse
  // that so the toast shows the human-readable message from the server (in
  // particular, the 409 same-seller-conflict message).
  async function readErrorDetail(r: Response, fallback: string): Promise<string> {
    try {
      const body = await r.json();
      if (body && typeof body.detail === "string") return body.detail;
    } catch {
      /* not JSON */
    }
    return fallback;
  }

  async function doMap() {
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE_PUBLIC}/api/mappings/manual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rayna_option_id: raynaOptionId,
          competitor_option_id: competitorOptionId,
        }),
      });
      if (!r.ok) {
        const msg = await readErrorDetail(r, `Mapping failed (${r.status})`);
        toast.error(msg);
        return;
      }
      toast.success("Mapped — returning to workspace");
      router.push(
        `/?productId=${productId}&raynaOptionId=${raynaOptionId}`,
      );
    } finally {
      setBusy(false);
    }
  }

  async function doUnmap(mappingId: number) {
    setBusy(true);
    try {
      const r = await fetch(
        `${API_BASE_PUBLIC}/api/mappings/${mappingId}`,
        { method: "DELETE" },
      );
      if (!r.ok && r.status !== 204) {
        const msg = await readErrorDetail(r, `Unmap failed (${r.status})`);
        toast.error(msg);
        return;
      }
      toast.success("Unmapped");
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  async function doRemap() {
    if (!existingMapping) return;
    setBusy(true);
    try {
      const del = await fetch(
        `${API_BASE_PUBLIC}/api/mappings/${existingMapping.mapping_id}`,
        { method: "DELETE" },
      );
      if (!del.ok && del.status !== 204) {
        const msg = await readErrorDetail(del, `Unmap failed (${del.status})`);
        toast.error(msg);
        return;
      }
      const put = await fetch(`${API_BASE_PUBLIC}/api/mappings/manual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rayna_option_id: raynaOptionId,
          competitor_option_id: competitorOptionId,
        }),
      });
      if (!put.ok) {
        const msg = await readErrorDetail(put, `Re-map failed (${put.status})`);
        toast.error(msg);
        return;
      }
      toast.success("Re-mapped — returning to workspace");
      router.push(
        `/?productId=${productId}&raynaOptionId=${raynaOptionId}`,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-[13px] border border-[#EBECEF] bg-white px-5 py-4 flex items-center gap-4 flex-wrap">
      {mappedToThis ? (
        <>
          <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-[8px] text-[12.5px] font-semibold bg-[#E8F5EC] text-[#197A45] border border-[#BFE3CB]">
            <Check className="w-3.5 h-3.5" strokeWidth={3} />
            Mapped to {truncate(raynaOptionName, 40)}
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={() => doUnmap(existingMapping!.mapping_id)}
            className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[8px] text-[12px] font-semibold text-[#9AA0A8] hover:bg-[#FBEAE8] hover:text-[#B5342C] disabled:opacity-50 transition-colors"
          >
            {busy ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <X className="w-3.5 h-3.5" />
            )}
            Unmap
          </button>
        </>
      ) : mappedElsewhere ? (
        <>
          <span className="inline-flex items-start gap-2 text-[12.5px] text-[#9A6510]">
            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
            <span>
              Currently mapped to{" "}
              <span className="font-semibold">
                {truncate(existingMapping!.rayna_option_name, 60)}
              </span>
              . Re-mapping will replace that link.
            </span>
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={doRemap}
            className="ml-auto inline-flex items-center gap-1.5 px-4 py-2 rounded-[9px] text-[12.5px] font-semibold bg-[#0E6F6A] text-white hover:bg-[#0B5853] shadow-sm shadow-[#0E6F6A]/20 disabled:opacity-50 transition-colors"
          >
            {busy ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Plus className="w-3.5 h-3.5" strokeWidth={3} />
            )}
            Re-map to this option
          </button>
        </>
      ) : (
        <>
          <div className="text-[12.5px] text-[#5C6069]">
            Confirm this is a like-for-like match for{" "}
            <span className="font-semibold text-[#1F2127]">
              {truncate(raynaOptionName, 40)}
            </span>
            .
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={doMap}
            className="ml-auto inline-flex items-center gap-1.5 px-4 py-2 rounded-[9px] text-[12.5px] font-semibold bg-[#0E6F6A] text-white hover:bg-[#0B5853] shadow-sm shadow-[#0E6F6A]/20 disabled:opacity-50 transition-colors"
          >
            {busy ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Plus className="w-3.5 h-3.5" strokeWidth={3} />
            )}
            Map to this Rayna option
          </button>
        </>
      )}
    </div>
  );
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s;
}
