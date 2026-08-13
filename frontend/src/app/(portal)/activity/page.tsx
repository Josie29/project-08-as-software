import { redirect } from "next/navigation";

import { ActivityTable } from "@/components/ActivityTable";
import { PortalFrame } from "@/components/PortalFrame";
import { Eyebrow } from "@/components/ui";
import { getActivity } from "@/lib/api";

export const fetchCache = "only-no-store";

/** The patient's own access log — who touched their record, and whether it was allowed. */
export default async function ActivityPage() {
  const entries = await getActivity();
  if (entries === null) redirect("/verify");

  return (
    <PortalFrame>
      <div className="grid gap-1.5">
        <Eyebrow>Compliance</Eyebrow>
        <h1 className="text-2xl">Access log</h1>
        <p className="max-w-[44rem] text-[0.9375rem] text-ink-2">
          Every time your images or report are opened, it is written here — including attempts that
          were refused. Entries can only be added, never edited or removed.
        </p>
      </div>

      <ActivityTable entries={entries} />
    </PortalFrame>
  );
}
