import { NextResponse } from "next/server";

import { requireAccessToken } from "@/lib/api";

/**
 * Create a share link on behalf of the signed-in patient.
 *
 * The token is attached here on the server rather than in the browser, so it never sits in
 * client-side JavaScript.
 *
 * @param request - Carries the share request body.
 * @returns The API's response, passed through unchanged.
 */
export async function POST(request: Request) {
  const token = await requireAccessToken();
  const upstream = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/shares`, {
    method: "POST",
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: await request.text(),
  });

  return NextResponse.json(await upstream.json().catch(() => ({})), {
    status: upstream.status,
    headers: { "Cache-Control": "private, no-store, max-age=0" },
  });
}
