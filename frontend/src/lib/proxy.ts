import "server-only";

import { NextResponse } from "next/server";

import { requireAccessToken } from "@/lib/api";

/** PHI must never be stored by a shared cache, and never persisted by the browser. */
const NO_STORE = "private, no-store, max-age=0";

/**
 * Forward a JSON request to the portal API on behalf of the signed-in patient.
 *
 * The access token is attached here, on the server, so it never sits in client-side
 * JavaScript. The upstream status is passed through unchanged rather than collapsed to
 * ok/failed, because the UI branches on it — a 409 means someone else took the slot and a
 * 422 means the request broke a policy rule, and those read very differently to a patient.
 *
 * @param path - API path beginning with a slash.
 * @param init - Method and body for the upstream call.
 * @returns The API's response, passed through with caching suppressed.
 */
export async function proxyJson(path: string, init: RequestInit = {}): Promise<NextResponse> {
  const token = await requireAccessToken();
  const upstream = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...init.headers,
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  });

  return NextResponse.json(await upstream.json().catch(() => ({})), {
    status: upstream.status,
    headers: { "Cache-Control": NO_STORE },
  });
}
