import { Topbar } from "@/components/Topbar";
import type { SessionUser } from "@/lib/api";

interface Props {
  // Kept as optional for source-compat with existing callers — the Topbar
  // no longer renders a per-page title now that navigation lives in the
  // top tabs. Each screen renders its own heading inside the content area.
  title?: string;
  subtitle?: string;
  // Resolved server-side by requireSession(); the Topbar needs it to decide
  // which tabs to show and who to name in the account menu.
  user: SessionUser;
  children: React.ReactNode;
}

export function AppLayout({ children, user }: Props) {
  return (
    <div className="flex flex-col h-screen w-full overflow-hidden bg-[#F8F9FB]">
      <Topbar user={user} />
      <main className="flex-1 overflow-y-auto min-h-0">
        <div className="page-enter h-full flex flex-col min-h-0">{children}</div>
      </main>
    </div>
  );
}
