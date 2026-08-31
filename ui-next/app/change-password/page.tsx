import Image from "next/image";
import { ChangePasswordForm } from "@/components/ChangePasswordForm";
import { requireSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function ChangePasswordPage() {
  const user = await requireSession({ allowPasswordChange: true });
  const forced = user.must_change_password;

  return (
    <div className="min-h-screen w-full bg-[#F8F9FB] flex items-center justify-center px-4">
      <div className="w-full max-w-[400px]">
        <div className="flex items-center gap-2.5 mb-7">
          <Image
            src="/rayna-logo.png"
            alt=""
            width={116}
            height={34}
            className="h-[34px] w-auto"
            priority
          />
          <span className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[#98A2B3] border-l border-[#E4E7EC] pl-2.5">
            Price Intelligence
          </span>
        </div>

        <div className="bg-white border border-[#E4E7EC] rounded-[14px] px-6 py-6 shadow-[0_1px_3px_rgba(16,24,40,0.06)]">
          <h1 className="text-[18px] font-bold text-[#101828] tracking-[-0.01em]">
            {forced ? "Choose your password" : "Change password"}
          </h1>
          <p className="text-[12.5px] text-[#667085] mt-1 mb-5 leading-relaxed">
            {forced ? (
              <>
                You&rsquo;re signed in as{" "}
                <span className="font-semibold text-[#344054]">{user.email}</span>{" "}
                with a temporary password. Set your own before continuing —
                nothing else is available until you do.
              </>
            ) : (
              <>
                Signed in as{" "}
                <span className="font-semibold text-[#344054]">{user.email}</span>.
                Changing this signs out your other sessions.
              </>
            )}
          </p>
          <ChangePasswordForm forced={forced} />
        </div>
      </div>
    </div>
  );
}
