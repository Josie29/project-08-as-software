import { defineConfig, devices } from "@playwright/test";

/**
 * Accessibility and viewport checks run against a locally running stack.
 *
 * They are not wired into CI: the seeded imaging assets live in Supabase Storage, so a
 * meaningful run needs the project's real credentials rather than the throwaway Postgres
 * the pytest suite uses. Run them with `npm run test:e2e` alongside `uvicorn` and
 * `next dev`.
 */
export default defineConfig({
  testDir: "./src/__tests__/e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    ...devices["Desktop Chrome"],
  },
});
