"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Loader2, X } from "lucide-react";
import { API_BASE_PUBLIC } from "@/lib/api";
import { useToast } from "@/components/Toast";

export function UnmapButton({ mappingId }: { mappingId: number }) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [, startTransition] = useTransition();

  async function unmap() {
    if (busy) return;
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE_PUBLIC}/api/mappings/${mappingId}`, {
        method: "DELETE",
      });
      if (!r.ok && r.status !== 204) {
        toast.error(`Unmap failed (${r.status})`);
        return;
      }
      toast.success("Unmapped");
      startTransition(() => router.refresh());
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      disabled={busy}
      onClick={unmap}
      className="inline-flex items-center gap-1 px-2 py-1 rounded-[6px] text-[11px] font-semibold text-[#9AA0A8] hover:bg-[#FBEAE8] hover:text-[#B5342C] disabled:opacity-50 transition-colors"
      title="Unmap"
    >
      {busy ? (
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
      ) : (
        <X className="w-3.5 h-3.5" />
      )}
      Unmap
    </button>
  );
}
