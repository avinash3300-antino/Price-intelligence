"use client";

import { useEffect, useRef } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  body?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  // Close on Escape, focus the confirm button when the dialog opens.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKey);
    // Focus after paint so the layout is ready.
    const t = setTimeout(() => confirmRef.current?.focus(), 20);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearTimeout(t);
    };
  }, [open, busy, onCancel]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
    >
      <button
        type="button"
        aria-label="Dismiss dialog"
        onClick={() => !busy && onCancel()}
        className="absolute inset-0 bg-[#101828]/40 backdrop-blur-[1px]"
        tabIndex={-1}
      />
      <div className="relative w-full max-w-[440px] bg-white rounded-[12px] border border-[#E4E7EC] shadow-[0_20px_50px_rgba(16,24,40,0.18)] overflow-hidden">
        <div className="px-5 pt-5 pb-4 flex items-start gap-3">
          {danger && (
            <span className="shrink-0 w-9 h-9 rounded-full bg-[#FEE4E2] text-[#B42318] inline-flex items-center justify-center">
              <AlertTriangle className="w-[18px] h-[18px]" strokeWidth={2.2} />
            </span>
          )}
          <div className="min-w-0 flex-1">
            <h3
              id="confirm-dialog-title"
              className="text-[15px] font-semibold text-[#101828] tracking-[-0.01em]"
            >
              {title}
            </h3>
            {body && (
              <div className="text-[12.5px] text-[#475467] leading-relaxed mt-2">
                {body}
              </div>
            )}
          </div>
        </div>
        <div className="px-5 py-3.5 bg-[#F9FAFB] border-t border-[#E4E7EC] flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="px-3.5 py-2 text-[12.5px] font-semibold text-[#344054] bg-white border border-[#D0D5DD] rounded-[8px] hover:bg-[#F2F4F7] disabled:opacity-50 transition-colors"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className={`inline-flex items-center gap-1.5 px-3.5 py-2 text-[12.5px] font-semibold text-white rounded-[8px] disabled:opacity-70 transition-colors ${
              danger
                ? "bg-[#D92D20] hover:bg-[#B42318]"
                : "bg-[#EA580C] hover:bg-[#C2410C]"
            }`}
          >
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
