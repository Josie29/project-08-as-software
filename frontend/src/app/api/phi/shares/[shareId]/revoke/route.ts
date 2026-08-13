import { proxyJson } from "@/lib/proxy";

/**
 * Switch off one of the patient's share links.
 *
 * @param _request - Unused.
 * @param context - Route parameters, which are a promise in this version of Next.
 * @returns The API's response.
 */
export async function POST(_request: Request, context: { params: Promise<{ shareId: string }> }) {
  const { shareId } = await context.params;
  return proxyJson(`/shares/${shareId}/revoke`, { method: "POST" });
}
