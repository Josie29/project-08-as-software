import { NextResponse } from "next/server";

import { requireAccessToken } from "@/lib/api";

/**
 * Fetch one clip's frame manifest on behalf of the signed-in patient.
 *
 * Requested when the viewer opens rather than when the gallery renders: the API writes one
 * audit entry per manifest read, and that entry should mean the patient opened the clip,
 * not that a page listing it happened to load.
 *
 * @param _request - The incoming request; unused.
 * @param context - Route parameters, which are a promise in this version of Next.
 * @returns The manifest JSON, or the API's status on failure.
 */
export async function GET(_request: Request, context: { params: Promise<{ clipId: string }> }) {
  const { clipId } = await context.params;
  const token = await requireAccessToken();
  const upstream = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/cine/${clipId}/manifest`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });

  if (!upstream.ok) {
    return new NextResponse(null, { status: upstream.status });
  }

  return NextResponse.json(await upstream.json(), {
    headers: { "Cache-Control": "private, no-store, max-age=0" },
  });
}
