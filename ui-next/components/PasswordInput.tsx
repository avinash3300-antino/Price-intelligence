"use client";

import { useId, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

interface Props {
  label: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete?: string;
  required?: boolean;
  autoFocus?: boolean;
  minLength?: number;
  hint?: string;
  id?: string;
}

/**
 * Password field with a reveal toggle.
 *
 * Typing a password you cannot see is the main reason people mistype one, and
 * these are handed over by an administrator rather than remembered — so being
 * able to check what was pasted matters more here than the shoulder-surfing
 * risk on an internal tool.
 *
 * Starts hidden, and the button reports its state to screen readers rather
 * than relying on the icon alone.
 */
export function PasswordInput({
  label,
  value,
  onChange,
  autoComplete = "current-password",
  required,
  autoFocus,
  minLength,
  hint,
  id,
}: Props) {
  const generated = useId();
  const inputId = id ?? generated;
  const [shown, setShown] = useState(false);

  return (
    <div>
      <label
        htmlFor={inputId}
        className="block text-[12px] font-semibold text-[#344054] mb-1.5"
      >
        {label}
      </label>
      <div className="relative">
        <input
          id={inputId}
          type={shown ? "text" : "password"}
          autoComplete={autoComplete}
          required={required}
          autoFocus={autoFocus}
          minLength={minLength}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full pl-3 pr-10 py-2.5 text-[13.5px] bg-white border border-[#D0D5DD] rounded-[9px] outline-none focus:border-[#EA580C] focus:ring-2 focus:ring-[#FFEDD5] transition"
        />
        <button
          type="button"
          onClick={() => setShown((v) => !v)}
          // tabIndex -1 keeps Tab going straight from the field to the submit
          // button, which is what someone filling in a login form expects.
          tabIndex={-1}
          aria-label={shown ? "Hide password" : "Show password"}
          aria-pressed={shown}
          title={shown ? "Hide password" : "Show password"}
          className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-[7px] text-[#98A2B3] hover:text-[#344054] hover:bg-[#F2F4F7] transition"
        >
          {shown ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
      {hint && <p className="text-[11px] text-[#98A2B3] mt-1.5">{hint}</p>}
    </div>
  );
}
