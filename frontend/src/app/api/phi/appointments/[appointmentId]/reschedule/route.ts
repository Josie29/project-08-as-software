import { proxyJson } from "@/lib/proxy";

/**
 * Move one of the patient's appointments to another open slot.
 *
 * @param request - Carries the target slot id.
 * @param context - Route parameters, which are a promise in this version of Next.
 * @returns The API's response, including a 409 when the target was taken first.
 */
export async function POST(
  request: Request,
  context: { params: Promise<{ appointmentId: string }> },
) {
  const { appointmentId } = await context.params;
  return proxyJson(`/appointments/${appointmentId}/reschedule`, {
    method: "POST",
    body: await request.text(),
  });
}
