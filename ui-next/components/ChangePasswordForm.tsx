"use client";

import { useState } from "react";
import { AlertCircle, KeyRound, Loader2 } from "lucide-react";

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

  const field =
    "w-full px-3 py-2.5 text-[13.5px] bg-white border border-[#D0D5DD] rounded-[9px] outline-none focus:border-[#EA580C] focus:ring-2 focus:ring-[#FFEDD5] transition";
  const label = "block text-[12px] font-semibold text-[#344054] mb-1.5";

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <label htmlFor="cur" className={label}>
          {forced ? "Temporary password" : "Current password"}
        </label>
        <input
          id="cur"
          type="password"
          autoComplete="current-password"
          required
          autoFocus
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          className={field}
        />
      </div>
      <div>
        <label htmlFor="new" className={label}>
          New password
        </label>
        <input
          id="new"
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          value={next}
          onChange={(e) => setNext(e.target.value)}
          className={field}
        />
        <p className="text-[11px] text-[#98A2B3] mt-1.5">
          At least 8 characters. Length matters more than symbols.
        </p>
      </div>
      <div>
        <label htmlFor="confirm" className={label}>
          Confirm new password
        </label>
        <input
          id="confirm"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          className={field}
        />
      </div>

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
