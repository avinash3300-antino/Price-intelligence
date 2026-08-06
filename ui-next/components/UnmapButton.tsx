"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Loader2, X } from "lucide-react";
import { API_BASE_PUBLIC } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ConfirmDialog } from "@/components/ConfirmDialog";

export function UnmapButton({ mappingId }: { mappingId: number }) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [, startTransition] = useTransition();

  async function doUnmap() {
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
      setConfirming(false);
      startTransition(() => router.refresh());
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        disabled={busy}
        onClick={() => setConfirming(true)}
        className="inline-flex items-center gap-1 px-2 py-1  text-[11px] font-semibold text-[#98A2B3] hover:bg-[#FBEAE8] hover:text-[#B5342C] disabled:opacity-50 transition-colors"
        title="Unmap"
      >
        {busy ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <X className="w-3.5 h-3.5" />
        )}
        Unmap
      </button>
      <ConfirmDialog
        open={confirming}
        title="Unmap this pair?"
        body="This removes the confirmed link between the Rayna option and the competitor option. The competitor row stays in the workspace so you can remap it."
        confirmLabel="Unmap"
        danger
        busy={busy}
        onConfirm={doUnmap}
        onCancel={() => !busy && setConfirming(false)}
      />
    </>
  );
}
