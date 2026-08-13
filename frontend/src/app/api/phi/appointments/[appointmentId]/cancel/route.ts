import { proxyJson } from "@/lib/proxy";

/**
 * Cancel one of the patient's appointments, freeing its slot.
 *
 * @param request - Carries an optional reason.
 * @param context - Route parameters, which are a promise in this version of Next.
 * @returns The API's response, including a 422 inside the minimum-notice window.
 */
export async function POST(
  request: Request,
  context: { params: Promise<{ appointmentId: string }> },
) {
  const { appointmentId } = await context.params;
  return proxyJson(`/appointments/${appointmentId}/cancel`, {
    method: "POST",
    body: await request.text(),
  });
}
