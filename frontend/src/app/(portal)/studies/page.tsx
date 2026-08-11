import { redirect } from "next/navigation";

import { PatientCard } from "@/components/PatientCard";
import { Rail } from "@/components/Rail";
import { StudyGallery, type StudyWithImages } from "@/components/StudyGallery";
import { Eyebrow } from "@/components/ui";
import { apiFetch, ApiError, getStudies, getStudyImages } from "@/lib/api";
import type { PatientProfile } from "@/components/PatientCard";

/** Every response here is one patient's PHI, so nothing on this route may be cached. */
export const fetchCache = "only-no-store";

/** The patient's imaging screen. */
export default async function StudiesPage() {
  const studies = await getStudies();
  // A signed-in patient who has not passed the identity check gets sent to that step
  // rather than an error — the API already refused the data.
  if (studies === null) redirect("/verify");

  let profile: PatientProfile | null = null;
  try {
    profile = await apiFetch<PatientProfile>("/me");
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
  }

  const withImages: StudyWithImages[] = await Promise.all(
    studies.map(async (study) => ({ study, images: await getStudyImages(study.id) })),
  );

  const imageTotal = withImages.reduce((sum, entry) => sum + entry.images.length, 0);

  return (
    <>
      <div className="grid gap-6 lg:sticky lg:top-[5.25rem]">
        <Rail counts={{ "/studies": imageTotal }} />
        {profile ? <PatientCard profile={profile} /> : null}
      </div>

      <main className="grid gap-6">
        <div className="grid gap-1.5">
          <Eyebrow>Your imaging</Eyebrow>
          <h1 className="text-2xl">Images and cine clips</h1>
          <p className="max-w-[44rem] text-[0.9375rem] text-ink-2">
            Only studies from visits you have already completed appear here. Open any image to
            zoom and pan.
          </p>
        </div>

        <StudyGallery studies={withImages} />
      </main>
    </>
  );
}
