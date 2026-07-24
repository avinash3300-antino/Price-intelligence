"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";

interface Props {
  title: string;
  subtitle?: string;
}

export function Topbar({ title, subtitle }: Props) {
  const router = useRouter();
  const [spinning, setSpinning] = useState(false);

  function handleRefresh() {
    if (spinning) return;
    setSpinning(true);
    router.refresh();
    setTimeout(() => setSpinning(false), 900);
  }

  return (
    <header className="h-[60px] shrink-0 bg-white border-b border-[#EBECEF] flex items-center px-7 gap-[18px]">
      <div className="leading-[1.25] min-w-0">
        <div className="text-[15px] font-semibold -tracking-[0.01em] truncate">
          {title}
        </div>
        {subtitle && (
          <div className="text-[11.5px] text-[#8A8F98] font-normal truncate">
            {subtitle}
          </div>
        )}
      </div>

      <div className="ml-auto flex items-center gap-[14px]">
        <div className="flex items-center bg-[#F2F3F5] border border-[#E7E8EB] rounded-[9px] p-[3px] gap-0.5">
          <button
            type="button"
            className="flex items-center gap-[7px] px-[11px] py-[5px] rounded-[7px] text-[12.5px] font-semibold bg-white text-[#0E6F6A] shadow-sm transition-colors"
          >
            <span className="text-[13px]">🇦🇪</span>
            UAE · AED
          </button>
          <button
            type="button"
            disabled
            className="flex items-center gap-[7px] px-[11px] py-[5px] rounded-[7px] text-[12.5px] font-medium bg-transparent text-[#B6BAC1] cursor-not-allowed"
          >
            <span className="text-[13px] grayscale opacity-70">🇮🇳</span>
            India · INR
            <span className="text-[9.5px] font-semibold bg-[#EDEEF1] text-[#9AA0A8] px-[6px] py-px rounded-[5px] tracking-[0.03em]">
              SOON
            </span>
          </button>
        </div>

        <div className="w-px h-[26px] bg-[#EBECEF]" />

        <div className="flex items-center gap-[9px]">
          <button
            type="button"
            onClick={handleRefresh}
            title="Refresh"
            className="w-[34px] h-[34px] rounded-[9px] border border-[#E2E3E7] bg-white flex items-center justify-center text-[#5C6069] hover:bg-[#F4F5F7] hover:border-[#D5D7DC] transition-colors"
          >
            <RefreshCw
              className={`w-4 h-4 ${spinning ? "animate-spin" : ""}`}
              strokeWidth={2}
            />
          </button>
        </div>

        <div className="w-[32px] h-[32px] rounded-full bg-gradient-to-br from-[#3A8C85] to-[#0E6F6A] text-white flex items-center justify-center text-[12.5px] font-semibold">
          AK
        </div>
      </div>
    </header>
  );
}
