import { redirect } from "next/navigation";

import { PortalFrame } from "@/components/PortalFrame";
import { ShareList } from "@/components/ShareList";
import { Eyebrow } from "@/components/ui";
import { getShares } from "@/lib/api";

export const fetchCache = "only-no-store";

/** Links the patient has shared, with the ability to switch any of them off. */
export default async function SharesPage() {
  const shares = await getShares();
  if (shares === null) redirect("/verify");

  const active = shares.filter(
    (share) => share.revoked_at === null && new Date(share.expires_at) > new Date(),
  ).length;

  return (
    <PortalFrame counts={{ "/shares": active }}>
      <div className="grid gap-1.5">
        <Eyebrow>Secure sharing</Eyebrow>
        <h1 className="text-2xl">Links you&rsquo;ve shared</h1>
        <p className="max-w-[44rem] text-[0.9375rem] text-ink-2">
          Every link expires on its own, and you can switch one off at any moment. The email carries
          the link and nothing else — no images, no report text, no health details.
        </p>
      </div>

      <ShareList initial={shares} />
    </PortalFrame>
  );
}
