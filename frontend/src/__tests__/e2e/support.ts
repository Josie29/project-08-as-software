import { expect, type Page } from "@playwright/test";

/** Demo credentials, published in the README. Synthetic data, never real. */
export const DEMO = {
  email: "patient@demo.test",
  password: "PortalDemo!2026",
  accountId: "AS-100241",
  dateOfBirth: "1991-06-24",
};

/** Phone width the brief's video is recorded at. */
export const PHONE = { width: 375, height: 812 };

/** Every patient-facing screen, with the heading that proves it rendered. */
export const SCREENS = [
  { path: "/studies", heading: "Images and cine clips" },
  { path: "/reports", heading: "Reports" },
  { path: "/shares", heading: "Links you’ve shared" },
  { path: "/appointments", heading: "Appointments" },
  { path: "/activity", heading: "Access log" },
] as const;

/**
 * Sign in and clear the identity gate.
 *
 * Both steps are exercised through the UI rather than seeded into storage: they are the
 * two controls standing between a session and protected health information, and a test
 * that skipped them would be checking a state the product never actually reaches.
 *
 * @param page - The page to authenticate.
 */
export async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(DEMO.email);
  await page.getByLabel("Password").fill(DEMO.password);
  await page.getByRole("button", { name: "Continue" }).click();

  await page.waitForURL("**/verify");
  await page.getByLabel("Patient ID").fill(DEMO.accountId);
  await page.getByLabel("Date of birth").fill(DEMO.dateOfBirth);
  await page.getByRole("button", { name: "Continue" }).click();

  await page.waitForURL("**/studies", { timeout: 30_000 });
}

/**
 * Assert the page does not scroll sideways.
 *
 * Horizontal overflow is the failure that makes a phone layout feel broken, and it is
 * invisible on a desktop viewport — so it is asserted rather than eyeballed.
 *
 * @param page - The page under test.
 * @param label - Included in the failure message.
 */
export async function expectNoHorizontalScroll(page: Page, label: string): Promise<void> {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    const widest = [...document.querySelectorAll<HTMLElement>("body *")]
      .filter((el) => el.getBoundingClientRect().right > root.clientWidth + 1)
      .map((el) => `${el.tagName.toLowerCase()}.${el.className}`.slice(0, 120));
    return {
      scrollWidth: root.scrollWidth,
      clientWidth: root.clientWidth,
      widest: widest.slice(0, 5),
    };
  });
  expect(
    overflow.scrollWidth,
    `${label} scrolls sideways; widest offenders: ${overflow.widest.join(" | ")}`,
  ).toBeLessThanOrEqual(overflow.clientWidth + 1);
}

/** Minimum comfortable tap target, in CSS pixels. */
const MIN_TAP_PX = 34;

/**
 * Assert every visible control is large enough to tap.
 *
 * @param page - The page under test.
 * @param label - Included in the failure message.
 */
export async function expectTappableControls(page: Page, label: string): Promise<void> {
  const small = await page.evaluate((min) => {
    const controls = [...document.querySelectorAll<HTMLElement>("button, a[href], select, input")];
    return controls
      .filter((el) => {
        if (el.getAttribute("type") === "radio" && el.classList.contains("sr-only")) return false;
        const box = el.getBoundingClientRect();
        if (box.width === 0 && box.height === 0) return false;
        return box.height < min || box.width < min;
      })
      .map((el) => `${el.tagName.toLowerCase()} "${(el.textContent ?? "").trim().slice(0, 24)}"`);
  }, MIN_TAP_PX);
  expect(small, `${label} has controls smaller than ${MIN_TAP_PX}px`).toEqual([]);
}
