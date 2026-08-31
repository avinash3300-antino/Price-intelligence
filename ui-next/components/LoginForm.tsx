"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { AlertCircle, Loader2, LogIn } from "lucide-react";
import { PasswordInput } from "@/components/PasswordInput";

export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // Same-origin: nginx in production, the Next rewrite in development.
      // The session cookie is httpOnly, so nothing here ever touches it —
      // the browser stores it and attaches it from then on.
      const r = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
        credentials: "include",
      });
      if (!r.ok) {
        let detail = "Sign-in failed.";
        try {
          detail = (await r.json())?.detail ?? detail;
        } catch {
          /* not JSON */
        }
        setError(detail);
        setBusy(false);
        return;
      }
      const me = await r.json();
      // A full navigation, not router.push — every page is server-rendered and
      // must re-fetch with the new cookie attached.
      window.location.href = me.must_change_password ? "/change-password" : "/";
    } catch {
      setError("Could not reach the server. Check your connection.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <label
          htmlFor="email"
          className="block text-[12px] font-semibold text-[#344054] mb-1.5"
        >
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          required
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@raynatours.com"
          className="w-full px-3 py-2.5 text-[13.5px] bg-white border border-[#D0D5DD] rounded-[9px] outline-none focus:border-[#EA580C] focus:ring-2 focus:ring-[#FFEDD5] transition"
        />
      </div>

      <PasswordInput
        id="password"
        label="Password"
        value={password}
        onChange={setPassword}
        placeholder="Enter your password"
        required
      />

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 border border-[#FECACA] bg-[#FEF2F2] rounded-[9px] px-3.5 py-2.5"
        >
          <AlertCircle className="w-4 h-4 text-[#B42318] mt-0.5 shrink-0" />
          <span className="text-[12.5px] text-[#7A271A] leading-relaxed">
            {error}
          </span>
        </div>
      )}

      <button
        type="submit"
        disabled={busy}
        className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-[9px] text-[13.5px] font-semibold bg-[#EA580C] text-white hover:bg-[#C2410C] disabled:opacity-60 disabled:pointer-events-none transition-colors"
      >
        {busy ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Signing in…
          </>
        ) : (
          <>
            <LogIn className="w-4 h-4" />
            Sign in
          </>
        )}
      </button>
    </form>
  );
}
