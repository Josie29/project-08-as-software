import { proxyJson } from "@/lib/proxy";

/**
 * List open slots for one provider.
 *
 * Re-fetched from the browser whenever the patient switches clinician, and again after a
 * booking so a slot someone else took disappears rather than lingering as bookable.
 *
 * @param request - Carries the optional `days` window.
 * @param context - Route parameters, which are a promise in this version of Next.
 * @returns The API's response.
 */
export async function GET(request: Request, context: { params: Promise<{ providerId: string }> }) {
  const { providerId } = await context.params;
  const days = new URL(request.url).searchParams.get("days") ?? "30";
  return proxyJson(`/providers/${providerId}/slots?days=${encodeURIComponent(days)}`);
}
