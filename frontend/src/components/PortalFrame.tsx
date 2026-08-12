import { redirect } from "next/navigation";

import type { PatientProfile } from "@/components/PatientCard";
import { PatientCard } from "@/components/PatientCard";
import { Rail } from "@/components/Rail";
import { ApiError, apiFetch } from "@/lib/api";
import { MOCK_RAIL_COUNTS } from "@/lib/mock";

/**
 * Chrome shared by every portal screen: the rail, the patient card, and the content column.
 *
 * The identity check happens here rather than in a layout because layouts are not
 * re-rendered on navigation, so a layout cannot gate its children.
 *
 * @param props.children - The screen's content.
 * @param props.counts - Rail badge counts to merge over the mock defaults.
 */
export async function PortalFrame({
  children,
  counts = {},
}: {
  children: React.ReactNode;
  counts?: Record<string, number>;
}) {
  let profile: PatientProfile | null = null;
  try {
    profile = await apiFetch<PatientProfile>("/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) redirect("/verify");
    if (!(error instanceof ApiError)) throw error;
  }

  return (
    <>
      <div className="grid gap-6 lg:sticky lg:top-[5.25rem]">
        <Rail counts={{ ...MOCK_RAIL_COUNTS, ...counts }} />
        {profile ? <PatientCard profile={profile} /> : null}
      </div>
      <main className="grid gap-6">{children}</main>
    </>
  );
}
