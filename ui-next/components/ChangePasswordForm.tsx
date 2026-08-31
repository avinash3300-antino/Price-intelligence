"use client";

import { useState } from "react";
import { AlertCircle, KeyRound, Loader2 } from "lucide-react";
import { PasswordInput } from "@/components/PasswordInput";

export function ChangePasswordForm({ forced }: { forced: boolean }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== confirm) {
      setError("The two new passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    const r = await fetch("/api/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: current, new_password: next }),
      credentials: "include",
    });
    if (!r.ok) {
      let detail = "Could not change the password.";
      try {
        detail = (await r.json())?.detail ?? detail;
      } catch {
        /* not JSON */
      }
      setError(detail);
      setBusy(false);
      return;
    }
    setDone(true);
    // The API re-issued the session cookie; a full navigation picks it up.
    window.location.href = "/";
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <PasswordInput
        id="cur"
        label={forced ? "Temporary password" : "Current password"}
        value={current}
        onChange={setCurrent}
        autoComplete="current-password"
        placeholder={forced ? "The password you were given" : "Your current password"}
        required
        autoFocus
      />
      <PasswordInput
        id="new"
        label="New password"
        value={next}
        onChange={setNext}
        autoComplete="new-password"
        placeholder="At least 8 characters"
        required
        minLength={8}
        hint="At least 8 characters. Length matters more than symbols."
      />
      <PasswordInput
        id="confirm"
        label="Confirm new password"
        value={confirm}
        onChange={setConfirm}
        autoComplete="new-password"
        placeholder="Type it again"
        required
      />

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 border border-[#FECACA] bg-[#FEF2F2] rounded-[9px] px-3.5 py-2.5"
        >
          <AlertCircle className="w-4 h-4 text-[#B42318] mt-0.5 shrink-0" />
          <span className="text-[12.5px] text-[#7A271A]">{error}</span>
        </div>
      )}

      <button
        type="submit"
        disabled={busy || done}
        className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-[9px] text-[13.5px] font-semibold bg-[#EA580C] text-white hover:bg-[#C2410C] disabled:opacity-60 disabled:pointer-events-none transition-colors"
      >
        {busy ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Saving…
          </>
        ) : (
          <>
            <KeyRound className="w-4 h-4" />
            Set new password
          </>
        )}
      </button>
    </form>
  );
}
