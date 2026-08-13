import { proxyJson } from "@/lib/proxy";

/**
 * Create a share link on behalf of the signed-in patient.
 *
 * @param request - Carries the share request body.
 * @returns The API's response, passed through unchanged.
 */
export async function POST(request: Request) {
  return proxyJson("/shares", { method: "POST", body: await request.text() });
}
