import "server-only";

import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";
import { redirect } from "next/navigation";

/**
 * Server-side Supabase client bound to the request's cookies.
 *
 * `cookies()` is asynchronous in this version of Next, and writes are only permitted from
 * a Server Function or Route Handler — hence the guarded `setAll`.
 *
 * @returns A server Supabase client.
 */
async function createServerSupabase() {
  const cookieStore = await cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => cookieStore.getAll(),
        setAll: (toSet) => {
          try {
            toSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options));
          } catch {
            // Called from a Server Component, where cookies are read-only. The session is
            // refreshed on the next Server Function or Route Handler instead.
          }
        },
      },
    },
  );
}

/**
 * Return the caller's access token, or redirect to the login screen.
 *
 * @returns The Supabase access token.
 */
export async function requireAccessToken(): Promise<string> {
  const supabase = await createServerSupabase();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session) redirect("/login");
  return session.access_token;
}

/** A failed API call, carrying the status so callers can branch on 403 vs 404. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code?: string,
  ) {
    super(`API request failed with ${status}`);
  }
}

/**
 * Call the portal API on behalf of the signed-in patient.
 *
 * `no-store` is explicit rather than relying on the framework default: every response here
 * is one patient's protected health information and must never be reused for another
 * request or another person.
 *
 * @param path - API path beginning with a slash.
 * @param init - Additional fetch options.
 * @returns The parsed JSON body.
 * @throws ApiError If the API returns a non-2xx status.
 */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await requireAccessToken();
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...init.headers,
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(response.status, body?.detail?.code);
  }
  return (await response.json()) as T;
}

/** A study as shown in the patient's list. */
export interface StudySummary {
  id: string;
  performed_at: string;
  description: string | null;
  image_count: number;
}

/** Image metadata for one study. */
export interface ImageSummary {
  id: string;
  sequence: number;
  width: number;
  height: number;
  has_thumbnail: boolean;
}

/**
 * Fetch the caller's completed studies.
 *
 * @returns The studies, or null when identity verification is still required.
 */
export async function getStudies(): Promise<StudySummary[] | null> {
  try {
    return await apiFetch<StudySummary[]>("/studies");
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return null;
    throw error;
  }
}

/**
 * Fetch image metadata for one study.
 *
 * @param studyId - The study to list.
 * @returns The study's images.
 */
export async function getStudyImages(studyId: string): Promise<ImageSummary[]> {
  return apiFetch<ImageSummary[]>(`/studies/${studyId}/images`);
}

/** A cine clip as it appears alongside a study's stills. */
export interface CineClipSummary {
  id: string;
  study_id: string;
  sequence: number;
  frame_count: number;
  default_fps: number;
  available_frame_count: number;
}

/** One entry in a clip's manifest. */
export interface CineFrameEntry {
  sequence: number;
  available: boolean;
}

/** The ordered frame list for one clip. */
export interface CineManifest {
  id: string;
  study_id: string;
  frame_count: number;
  default_fps: number;
  frames: CineFrameEntry[];
}

/**
 * Fetch cine clips for one study.
 *
 * @param studyId - The study to list.
 * @returns The study's clips.
 */
export async function getStudyClips(studyId: string): Promise<CineClipSummary[]> {
  return apiFetch<CineClipSummary[]>(`/studies/${studyId}/cine`);
}

/** A report as it appears in the patient's list. */
export interface ReportSummary {
  id: string;
  study_id: string;
  title: string;
  status: "final" | "amended";
  signed_at: string | null;
}

/** A full report, including its body. */
export interface ReportDetail extends ReportSummary {
  body: string;
}

/**
 * Fetch the caller's signed reports.
 *
 * @returns The reports, or null when identity verification is still required.
 */
export async function getReports(): Promise<ReportSummary[] | null> {
  try {
    return await apiFetch<ReportSummary[]>("/reports");
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return null;
    throw error;
  }
}

/**
 * Fetch one signed report in full.
 *
 * @param reportId - The report to read.
 * @returns The report.
 */
export async function getReport(reportId: string): Promise<ReportDetail> {
  return apiFetch<ReportDetail>(`/reports/${reportId}`);
}

/** A share link as the patient sees it. Never carries the token. */
export interface ShareRecord {
  id: string;
  resource_type: "image" | "report";
  resource_id: string;
  recipient_email: string;
  expires_at: string;
  revoked_at: string | null;
  access_count: number;
}

/** The response to minting a link. The token appears here once. */
export interface CreatedShare {
  share: ShareRecord;
  link: string;
  email_sent: boolean;
  email_error: string | null;
}

/**
 * Fetch the links this patient has created.
 *
 * @returns Their links, or null when identity verification is still required.
 */
export async function getShares(): Promise<ShareRecord[] | null> {
  try {
    return await apiFetch<ShareRecord[]>("/shares");
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return null;
    throw error;
  }
}
