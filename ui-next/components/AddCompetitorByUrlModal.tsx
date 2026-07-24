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
        className="w-full max-w-[640px] bg-white rounded-[14px] shadow-2xl ring-1 ring-black/5 border border-[#EBECEF] overflow-hidden"
      >
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-[#F1F2F4]">
          <div>
            <div className="text-[15px] font-semibold text-[#1F2127] flex items-center gap-2">
              <LinkIcon className="w-4 h-4 text-[#0E6F6A]" />
              Add competitor by URL
            </div>
            <div className="text-[12px] text-[#8A8F98] mt-1">
              {raynaOptionName ? (
                <>
                  Mapping target:{" "}
                  <span className="font-semibold text-[#3D424B]">
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
            className="text-[#8A8F98] hover:text-[#1F2127] p-1 rounded-md hover:bg-[#F4F5F7] disabled:opacity-40"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4">
          {disabledReason ? (
            <div className="text-[13px] text-[#8A8F98] py-4">{disabledReason}</div>
          ) : stage.kind === "input" ? (
            <InputForm
              url={url}
              setUrl={setUrl}
              note={note}
              setNote={setNote}
              onSubmit={() => submit()}
            />
          ) : stage.kind === "loading" ? (
            <div className="flex items-center gap-2.5 text-[13px] text-[#5C6069] py-6">
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
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[#5C6069]">
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
          className="mt-1 w-full px-3 py-2 rounded-[9px] border border-[#E2E3E7] focus:border-[#0E6F6A] focus:outline-none text-[13px] font-mono text-[#1F2127] placeholder:text-[#B0B4BB]"
          autoFocus
        />
      </label>
      <label className="block">
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[#5C6069]">
          Note (optional)
        </span>
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="e.g. Sourced from partner ping"
          className="mt-1 w-full px-3 py-2 rounded-[9px] border border-[#E2E3E7] focus:border-[#0E6F6A] focus:outline-none text-[13px] text-[#1F2127] placeholder:text-[#B0B4BB]"
        />
      </label>
      <div className="flex justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onSubmit}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-[9px] text-[13px] font-semibold bg-[#0E6F6A] text-white hover:bg-[#0B5853] transition-colors"
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
      <div className="rounded-[10px] border border-[#EFD8A6] bg-[#FBF1DE] px-3.5 py-3 flex items-start gap-2 text-[12.5px] text-[#7A4F08] leading-snug">
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
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[#5C6069] inline-flex items-center gap-1.5">
          <ClipboardPaste className="w-3.5 h-3.5" />
          Paste page content
        </span>
        <textarea
          value={pasted}
          onChange={(e) => setPasted(e.target.value)}
          rows={10}
          placeholder="Paste the product page's description, inclusions, price, etc."
          className="mt-1 w-full px-3 py-2 rounded-[9px] border border-[#E2E3E7] focus:border-[#0E6F6A] focus:outline-none text-[12.5px] text-[#1F2127] placeholder:text-[#B0B4BB] font-mono leading-relaxed resize-y"
          autoFocus
        />
      </label>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          disabled={pasted.trim().length < 200}
          onClick={onSubmit}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-[9px] text-[13px] font-semibold bg-[#0E6F6A] text-white hover:bg-[#0B5853] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
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
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <VerdictBadge verdict={data.verdict} confidence={data.confidence} />
        <span className="text-[11px] text-[#8A8F98] font-mono">
          {data.seller_domain}
        </span>
        {!data.saved_mapping && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-[6px] text-[10.5px] font-semibold bg-[#FBF1DE] text-[#9A6510] border border-[#EFD8A6]">
            <AlertTriangle className="w-3 h-3" />
            competitor saved, not mapped
          </span>
        )}
      </div>
      <div className="rounded-[10px] border border-[#EBECEF] bg-white px-4 py-3">
        <div className="text-[13px] text-[#1F2127] leading-snug mb-1.5">
          {data.competitor_name}
        </div>
        <div className="text-[12px] text-[#5C6069] tnum">
          <span className="font-semibold text-[#1F2127]">
            {fmtMoney(data.competitor_price, data.competitor_currency)}
          </span>
          <span className="mx-1.5 text-[#D5D7DC]">·</span>
          <span className="font-mono">
            {fmtBasis(data.competitor_pricing_basis)}
          </span>
        </div>
      </div>
      <div className="text-[12.5px] text-[#5C6069] italic border-l-2 border-[#EBECEF] pl-3 leading-snug">
        {data.diff_notes}
      </div>
      <div className="flex justify-end pt-1">
        <button
          type="button"
          onClick={onDone}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-[9px] text-[13px] font-semibold bg-[#0E6F6A] text-white hover:bg-[#0B5853] transition-colors"
        >
          Done
        </button>
      </div>
    </div>
  );
}
