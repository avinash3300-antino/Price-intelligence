import { redirect } from "next/navigation";
import { AppLayout } from "@/components/AppLayout";
import { AdminTabs } from "@/components/AdminTabs";
import { landingFor, requireSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function AdminPage() {
  const user = await requireSession();
  // The nav already hides this tab for non-admins; anyone arriving here has a
  // stale link, so send them somewhere they can actually use.
  if (user.role !== "admin") redirect(landingFor(user));

  return (
    <AppLayout user={user}>
      <div className="max-w-[1280px] mx-auto px-8 py-7 w-full">
        <AdminTabs currentUserId={user.id} />
      </div>
    </AppLayout>
  );
}
