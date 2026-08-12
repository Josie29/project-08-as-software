import { PortalFrame } from "@/components/PortalFrame";
import { PreviewNotice } from "@/components/PreviewNotice";
import { ShareList } from "@/components/ShareList";
import { Eyebrow } from "@/components/ui";
import { MOCK_SHARES } from "@/lib/mock";

export const fetchCache = "only-no-store";

/** Links the patient has shared, with the ability to switch any of them off. */
export default function SharesPage() {
  return (
    <PortalFrame>
      <div className="grid gap-1.5">
        <Eyebrow>Secure sharing</Eyebrow>
        <h1 className="text-2xl">Links you&rsquo;ve shared</h1>
        <p className="max-w-[44rem] text-[0.9375rem] text-ink-2">
          Every link expires on its own, and you can switch one off at any moment. The email
          carries the link and nothing else — no images, no report text, no health details.
        </p>
      </div>

      <PreviewNotice>
        The sharing API is not built yet. These links are examples, and switching one off
        changes only what you see on this page.
      </PreviewNotice>

      <ShareList initial={MOCK_SHARES} />
    </PortalFrame>
  );
}
