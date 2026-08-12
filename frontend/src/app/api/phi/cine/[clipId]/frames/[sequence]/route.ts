import { NextResponse } from "next/server";

import { requireAccessToken } from "@/lib/api";

/**
 * Stream one cine frame from the portal API.
 *
 * Same reason as the still-image proxy: an `<img>` cannot carry an Authorization header,
 * and frame bytes are PHI. The token is attached server-side and never enters a URL.
 *
 * @param _request - The incoming request; unused.
 * @param context - Route parameters, which are a promise in this version of Next.
 * @returns The frame bytes, or the API's status on failure.
 */
export async function GET(
  _request: Request,
  context: { params: Promise<{ clipId: string; sequence: string }> },
) {
  const { clipId, sequence } = await context.params;
  // Rejected here rather than forwarded, so a malformed segment cannot become part of an
  // upstream path.
  if (!/^\d{1,3}$/.test(sequence)) {
    return new NextResponse(null, { status: 404 });
  }

  const token = await requireAccessToken();
  const upstream = await fetch(
    `${process.env.NEXT_PUBLIC_API_BASE_URL}/cine/${clipId}/frames/${sequence}`,
    { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" },
  );

  if (!upstream.ok) {
    return new NextResponse(null, { status: upstream.status });
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "image/jpeg",
      "Cache-Control": "private, no-store, max-age=0",
    },
  });
}
