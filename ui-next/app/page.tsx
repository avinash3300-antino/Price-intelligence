import { AppLayout } from "@/components/AppLayout";
import { MappingView } from "@/components/MappingView";
import { getDashboard } from "@/lib/api";
import { requirePermission } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function MappingPage() {
  const user = await requirePermission("mapping.view");
  const { products } = await getDashboard();

  return (
    <AppLayout user={user}
      title="Mapping workspace"
      subtitle="Country → City → Product → see competitor pricing"
    >
      <div className="px-8 py-7 h-full flex flex-col min-h-0">
        <MappingView initialProducts={products} />
      </div>
    </AppLayout>
  );
}
