import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";

interface Props {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}

export function AppLayout({ title, subtitle, children }: Props) {
  return (
    <div className="flex h-screen w-full overflow-hidden bg-[#F6F7F9]">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar title={title} subtitle={subtitle} />
        <main className="flex-1 overflow-y-auto min-h-0">
          <div className="page-enter h-full flex flex-col min-h-0">{children}</div>
        </main>
      </div>
    </div>
  );
}
