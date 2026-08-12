import { NextResponse } from "next/server";

import { requireAccessToken } from "@/lib/api";

/**
 * Stream a clip's whole frame bundle from the portal API.
 *
 * The per-frame route still exists and is still the authorisation unit; this one is here
 * because a hundred frames fetched one at a time spends its entire budget on round trips.
 *
 * @param _request - The incoming request; unused.
 * @param context - Route parameters, which are a promise in this version of Next.
 * @returns The bundle bytes, or the API's status on failure.
 */
export async function GET(_request: Request, context: { params: Promise<{ clipId: string }> }) {
  const { clipId } = await context.params;
  const token = await requireAccessToken();
  const upstream = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/cine/${clipId}/frames`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });

  if (!upstream.ok) {
    return new NextResponse(null, { status: upstream.status });
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/vnd.portal.cine-frames",
      "Cache-Control": "private, no-store, max-age=0",
    },
  });
}
