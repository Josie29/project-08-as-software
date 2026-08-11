import { createBrowserClient } from "@supabase/ssr";

/**
 * Supabase client for the browser.
 *
 * Only ever holds the publishable key. Nothing it returns is trusted for authorization:
 * the session exists to obtain an access token, and every access decision is made by the
 * API after verifying that token's signature.
 *
 * @returns A browser Supabase client.
 */
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
