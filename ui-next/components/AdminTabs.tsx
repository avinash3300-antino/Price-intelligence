"use client";

import { useState } from "react";
import { ScrollText, Users } from "lucide-react";
import { AdminUsers } from "@/components/AdminUsers";
import { AdminAudit } from "@/components/AdminAudit";

/**
 * Two admin surfaces behind one route: who can do what, and what was done.
 *
 * Kept as local state rather than separate routes — switching is instant, and
 * neither view carries state worth putting in the URL.
 */
export function AdminTabs({ currentUserId }: { currentUserId: number }) {
  const [tab, setTab] = useState<"users" | "activity">("users");

  const base =
    "inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-[8px] text-[12.5px] font-semibold transition";

  return (
    <>
      <div className="inline-flex items-center gap-1 p-1 bg-[#F2F4F7] rounded-[10px] mb-5">
        <button
          type="button"
          onClick={() => setTab("users")}
          className={`${base} ${
            tab === "users"
              ? "bg-white text-[#101828] shadow-sm"
              : "text-[#667085] hover:text-[#101828]"
          }`}
        >
          <Users className="w-3.5 h-3.5" />
          Users
        </button>
        <button
          type="button"
          onClick={() => setTab("activity")}
          className={`${base} ${
            tab === "activity"
              ? "bg-white text-[#101828] shadow-sm"
              : "text-[#667085] hover:text-[#101828]"
          }`}
        >
          <ScrollText className="w-3.5 h-3.5" />
          Activity
        </button>
      </div>

      {tab === "users" ? <AdminUsers currentUserId={currentUserId} /> : <AdminAudit />}
    </>
  );
}
