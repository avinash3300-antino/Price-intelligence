import { AppLayout } from "@/components/AppLayout";
import { MappingView } from "@/components/MappingView";
import { getDashboard } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function MappingPage() {
  const { products } = await getDashboard();

  return (
    <AppLayout
      title="Mapping workspace"
      subtitle="Country → City → Product → see competitor pricing"
    >
      <div className="px-8 py-7 h-full flex flex-col min-h-0">
        <MappingView initialProducts={products} />
      </div>
    </AppLayout>
  );
}
