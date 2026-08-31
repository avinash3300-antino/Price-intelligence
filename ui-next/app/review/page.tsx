import { AppLayout } from "@/components/AppLayout";
import { ReviewQueueTable } from "@/components/ReviewQueueTable";
import { getReviewQueue } from "@/lib/api";
import { requirePermission } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function ReviewPage() {
  const user = await requirePermission("review.decide");
  const queue = await getReviewQueue();

  return (
    <AppLayout user={user}
      title="Mapping review"
      subtitle="Confirm or correct AI-proposed competitor matches"
    >
      <div className="max-w-[1480px] mx-auto px-8 py-7">
        <div className="mb-6 flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-[22px] font-semibold tracking-[-0.02em]">
              Review queue
            </h1>
            <p className="text-[13.5px] text-[#667085] mt-1">
              Mappings flagged by low confidence (&lt;0.70) or pricing-basis
              mismatch. Approve to keep, Reject to unmap — high-confidence
              matches are auto-approved and never surface here.
            </p>
          </div>
        </div>

        {queue.length === 0 ? (
          <div className="bg-white border border-dashed border-[#D5D7DC] rounded-[12px] px-8 py-16 text-center text-[#667085] text-[13px]">
            Empty queue — everything Claude found is either high-confidence or
            already reviewed.
          </div>
        ) : (
          <ReviewQueueTable items={queue} />
        )}
      </div>
    </AppLayout>
  );
}
