import { proxyJson } from "@/lib/proxy";

/**
 * Book an open slot for the signed-in patient.
 *
 * @param request - Carries the slot id and the submission key.
 * @returns The API's response, including a 409 when the slot was taken first.
 */
export async function POST(request: Request) {
  return proxyJson("/appointments", { method: "POST", body: await request.text() });
}
