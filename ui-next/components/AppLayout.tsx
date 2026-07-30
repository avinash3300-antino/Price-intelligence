import { Topbar } from "@/components/Topbar";

interface Props {
  // Kept as optional for source-compat with existing callers — the Topbar
  // no longer renders a per-page title now that navigation lives in the
  // top tabs. Each screen renders its own heading inside the content area.
  title?: string;
  subtitle?: string;
  children: React.ReactNode;
}

export function AppLayout({ children }: Props) {
  return (
    <div className="flex flex-col h-screen w-full overflow-hidden bg-[#F8F9FB]">
      <Topbar />
      <main className="flex-1 overflow-y-auto min-h-0">
        <div className="page-enter h-full flex flex-col min-h-0">{children}</div>
      </main>
    </div>
  );
}
