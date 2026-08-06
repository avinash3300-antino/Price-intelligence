"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowRight,
  ClipboardPaste,
  Loader2,
  Link as LinkIcon,
  X,
  AlertTriangle,
} from "lucide-react";
import {
  addCompetitorByUrl,
  type AddByUrlResponse,
} from "@/lib/api";
import { VerdictBadge } from "@/components/VerdictBadge";
import { useToast } from "@/components/Toast";
import { fmtBasis, fmtMoney } from "@/lib/format";

interface Props {
  raynaOptionId: number | null;
  raynaOptionName: string | null;
  onClose: () => void;
  onSaved: () => void;
}

type Stage =
  | { kind: "input" }
  | { kind: "loading"; label: string }
  | { kind: "needs_paste"; message: string }
  | { kind: "result"; data: AddByUrlResponse };

export function AddCompetitorByUrlModal({
  raynaOptionId,
  raynaOptionName,
  onClose,
  onSaved,
}: Props) {
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [pasted, setPasted] = useState("");
  const [stage, setStage] = useState<Stage>({ kind: "input" });
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && stage.kind !== "loading") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, stage.kind]);

  async function submit(pastedContent?: string) {
    if (!raynaOptionId) {
      toast.error("Pick a Rayna option first.");
      return;
    }
    if (!url.trim() || !/^https?:\/\//i.test(url.trim())) {
      toast.error("Enter a valid URL (must start with http:// or https://).");
      return;
    }
    setStage({
      kind: "loading",
      label: pastedContent ? "Extracting from pasted content…" : "Fetching URL…",
    });
    const outcome = await addCompetitorByUrl({
      rayna_option_id: raynaOptionId,
      url: url.trim(),
      pasted_content: pastedContent,
      note: note.trim() || undefined,
    });
    if (outcome.kind === "ok") {
      setStage({ kind: "result", data: outcome.data });
      if (outcome.data.saved_mapping) {
        toast.success(
          outcome.data.verdict === "different"
            ? "Saved — but Claude flagged it 'different' with low confidence"
            : `Mapped (${outcome.data.verdict})`,
        );
      } else {
        toast.success(
          "Competitor saved — Claude judged it 'different', not mapped",
        );
      }
      onSaved();
    } else if (outcome.kind === "needs_paste") {
      setStage({ kind: "needs_paste", message: outcome.message });
    } else {
      toast.error(outcome.message);
      setStage({ kind: "input" });
    }
  }

  if (!mounted) return null;

  const disabledReason = !raynaOptionId
    ? "Select a Rayna option in the workspace before adding a URL."
    : null;

  return createPortal(
    <div
      className="fixed inset-0 z-[80] bg-black/40 backdrop-blur-[2px] flex items-start justify-center pt-16 px-4"
      onClick={() => stage.kind !== "loading" && onClose()}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[640px] bg-white  shadow-2xl ring-1 ring-black/5 border border-[#E4E7EC] overflow-hidden"
      >
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-[#F2F4F7]">
          <div>
            <div className="text-[15px] font-semibold text-[#101828] flex items-center gap-2">
              <LinkIcon className="w-4 h-4 text-[#EA580C]" />
              Add competitor by URL
            </div>
            <div className="text-[12px] text-[#667085] mt-1">
              {raynaOptionName ? (
                <>
                  Mapping target:{" "}
                  <span className="font-semibold text-[#344054]">
                    {raynaOptionName.length > 60
                      ? raynaOptionName.slice(0, 57) + "…"
                      : raynaOptionName}
                  </span>
                </>
              ) : (
                <>Pick a Rayna option in the workspace first.</>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={stage.kind === "loading"}
            className="text-[#667085] hover:text-[#101828] p-1 rounded-[9px] hover:bg-[#F2F4F7] disabled:opacity-40"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4">
          {disabledReason ? (
            <div className="text-[13px] text-[#667085] py-4">{disabledReason}</div>
          ) : stage.kind === "input" ? (
            <InputForm
              url={url}
              setUrl={setUrl}
              note={note}
              setNote={setNote}
              onSubmit={() => submit()}
            />
          ) : stage.kind === "loading" ? (
            <div className="flex items-center gap-2.5 text-[13px] text-[#475467] py-6">
              <Loader2 className="w-4 h-4 animate-spin" />
              {stage.label}
            </div>
          ) : stage.kind === "needs_paste" ? (
            <PasteFallback
              message={stage.message}
              pasted={pasted}
              setPasted={setPasted}
              onSubmit={() => submit(pasted)}
            />
          ) : (
            <ResultView data={stage.data} onDone={onClose} />
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function InputForm({
  url,
  setUrl,
  note,
  setNote,
  onSubmit,
}: {
  url: string;
  setUrl: (v: string) => void;
  note: string;
  setNote: (v: string) => void;
  onSubmit: () => void;
}) {
  return (
    <div className="space-y-3">
      <label className="block">
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[#475467]">
          Competitor product URL
        </span>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSubmit();
          }}
          placeholder="https://www.viator.com/tours/…"
          className="mt-1 w-full px-3 py-2  border border-[#E2E3E7] focus:border-[#FED7AA] focus:outline-none text-[13px] font-mono text-[#101828] placeholder:text-[#D0D5DD]"
          autoFocus
        />
      </label>
      <label className="block">
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[#475467]">
          Note (optional)
        </span>
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="e.g. Sourced from partner ping"
          className="mt-1 w-full px-3 py-2  border border-[#E2E3E7] focus:border-[#FED7AA] focus:outline-none text-[13px] text-[#101828] placeholder:text-[#D0D5DD]"
        />
      </label>
      <div className="flex justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onSubmit}
          className="inline-flex items-center gap-1.5 px-4 py-2  text-[13px] font-semibold bg-[#EA580C] text-white hover:bg-[#C2410C] transition-colors"
        >
          Fetch & extract
          <ArrowRight className="w-3.5 h-3.5" strokeWidth={2.5} />
        </button>
      </div>
    </div>
  );
}

function PasteFallback({
  message,
  pasted,
  setPasted,
  onSubmit,
}: {
  message: string;
  pasted: string;
  setPasted: (v: string) => void;
  onSubmit: () => void;
}) {
  return (
    <div className="space-y-3">
      <div className=" border border-[#EFD8A6] bg-[#FBF1DE] px-3.5 py-3 flex items-start gap-2 text-[12.5px] text-[#7A4F08] leading-snug">
        <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
        <div>
          <div className="font-semibold">Couldn&rsquo;t fetch the page automatically.</div>
          <div className="opacity-90 mt-0.5">{message}</div>
          <div className="mt-1.5">
            Open the URL in your browser, select the description / details
            section, copy it, and paste below.
          </div>
        </div>
      </div>
      <label className="block">
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[#475467] inline-flex items-center gap-1.5">
          <ClipboardPaste className="w-3.5 h-3.5" />
          Paste page content
        </span>
        <textarea
          value={pasted}
          onChange={(e) => setPasted(e.target.value)}
          rows={10}
          placeholder="Paste the product page's description, inclusions, price, etc."
          className="mt-1 w-full px-3 py-2  border border-[#E2E3E7] focus:border-[#FED7AA] focus:outline-none text-[12.5px] text-[#101828] placeholder:text-[#D0D5DD] font-mono leading-relaxed resize-y"
          autoFocus
        />
      </label>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          disabled={pasted.trim().length < 200}
          onClick={onSubmit}
          className="inline-flex items-center gap-1.5 px-4 py-2  text-[13px] font-semibold bg-[#EA580C] text-white hover:bg-[#C2410C] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          title={
            pasted.trim().length < 200
              ? "Paste at least ~200 characters"
              : "Extract from pasted content"
          }
        >
          Extract from paste
          <ArrowRight className="w-3.5 h-3.5" strokeWidth={2.5} />
        </button>
      </div>
    </div>
  );
}

function ResultView({
  data,
  onDone,
}: {
  data: AddByUrlResponse;
  onDone: () => void;
}) {
  const options = data.all_options ?? [];
  const nMapped = options.filter((o) => o.is_target).length;
  const nSavedOnly = options.length - nMapped;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[13px] font-semibold text-[#101828]">
          Extracted {options.length} option{options.length === 1 ? "" : "s"}
        </span>
        <span className="text-[11px] text-[#667085] font-mono">
          {data.seller_domain}
        </span>
        {nMapped > 0 && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-[999px] text-[10.5px] font-semibold bg-[#ECFDF3] text-[#067647] border border-[#ABEFC6]">
            {nMapped} auto-mapped
          </span>
        )}
        {nSavedOnly > 0 && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-[999px] text-[10.5px] font-semibold bg-[#F2F4F7] text-[#475467] border border-[#E4E7EC]">
            {nSavedOnly} saved
          </span>
        )}
      </div>

      {nSavedOnly > 0 && (
        <div className="text-[11.5px] text-[#667085] leading-snug">
          Non-target options are saved as competitors and available in the
          workspace — map them to other Rayna options one at a time.
        </div>
      )}

      <div className="space-y-1.5 max-h-[360px] overflow-y-auto pr-1">
        {options.map((o) => (
          <div
            key={o.competitor_option_id}
            className={`border rounded-[9px] px-3 py-2 flex items-start gap-3 ${
              o.is_target
                ? "border-[#ABEFC6] bg-[#ECFDF3]"
                : "border-[#E4E7EC] bg-white"
            }`}
          >
            <div className="min-w-0 flex-1">
              <div className="text-[12.5px] font-semibold text-[#101828] leading-snug">
                {o.name}
              </div>
              <div className="text-[11px] text-[#475467] tnum mt-0.5">
                <span className="font-semibold text-[#101828]">
                  {fmtMoney(o.price, o.currency)}
                </span>
                <span className="mx-1.5 text-[#D0D5DD]">·</span>
                <span className="font-mono">{fmtBasis(o.pricing_basis)}</span>
              </div>
            </div>
            <div className="shrink-0 flex flex-col items-end gap-1">
              {o.is_target && (
                <span className="inline-flex items-center gap-1 px-1.5 py-[1px] rounded-[999px] text-[9.5px] font-bold uppercase tracking-[0.05em] bg-[#067647] text-white">
                  target
                </span>
              )}
              {o.verdict && o.confidence != null && (
                <VerdictBadge verdict={o.verdict} confidence={o.confidence} />
              )}
            </div>
          </div>
        ))}
      </div>

      {data.diff_notes && (
        <div className="text-[11.5px] text-[#475467] italic border-l-2 border-[#E4E7EC] pl-3 leading-snug">
          <span className="font-semibold not-italic text-[#344054]">
            Claude on the auto-mapped option:{" "}
          </span>
          {data.diff_notes}
        </div>
      )}

      <div className="flex justify-end pt-1">
        <button
          type="button"
          onClick={onDone}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-[9px] text-[13px] font-semibold bg-[#EA580C] text-white hover:bg-[#C2410C] transition-colors"
        >
          Done
        </button>
      </div>
    </div>
  );
}
