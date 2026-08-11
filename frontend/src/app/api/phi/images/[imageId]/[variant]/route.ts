import { NextResponse } from "next/server";

import { requireAccessToken } from "@/lib/api";

/**
 * Stream one image from the portal API.
 *
 * This proxy exists for one reason: an `<img>` element cannot send an Authorization
 * header, and PHI bytes must not be reachable without one. The token is attached here on
 * the server, so it never appears in a URL, in browser history, or in a referrer.
 *
 * Authorization and audit still happen in the API — this route adds no access decision of
 * its own.
 *
 * @param _request - The incoming request; unused.
 * @param context - Route parameters, which are a promise in this version of Next.
 * @returns The image bytes, or the API's status on failure.
 */
export async function GET(
  _request: Request,
  context: { params: Promise<{ imageId: string; variant: string }> },
) {
  const { imageId, variant } = await context.params;
  if (variant !== "file" && variant !== "thumbnail") {
    return new NextResponse(null, { status: 404 });
  }

  const token = await requireAccessToken();
  const upstream = await fetch(
    `${process.env.NEXT_PUBLIC_API_BASE_URL}/images/${imageId}/${variant}`,
    { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" },
  );

  if (!upstream.ok) {
    return new NextResponse(null, { status: upstream.status });
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "image/jpeg",
      // Matches the API. A shared cache holding one patient's scan would be a leak no
      // amount of server-side authorization could undo.
      "Cache-Control": "private, no-store, max-age=0",
    },
  });
}
