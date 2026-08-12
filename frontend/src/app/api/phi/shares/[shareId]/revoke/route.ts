import { NextResponse } from "next/server";

import { requireAccessToken } from "@/lib/api";

/**
 * Switch off one of the patient's share links.
 *
 * @param _request - Unused.
 * @param context - Route parameters, which are a promise in this version of Next.
 * @returns The API's response.
 */
export async function POST(
  _request: Request,
  context: { params: Promise<{ shareId: string }> },
) {
  const { shareId } = await context.params;
  const token = await requireAccessToken();
  const upstream = await fetch(
    `${process.env.NEXT_PUBLIC_API_BASE_URL}/shares/${shareId}/revoke`,
    { method: "POST", cache: "no-store", headers: { Authorization: `Bearer ${token}` } },
  );

  return NextResponse.json(await upstream.json().catch(() => ({})), {
    status: upstream.status,
    headers: { "Cache-Control": "private, no-store, max-age=0" },
  });
}
