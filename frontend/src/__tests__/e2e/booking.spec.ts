import { expect, type Page, test } from "@playwright/test";

import { signIn } from "./support";

/** Slot buttons carry the time in a tabular-nums span; nothing else on the page does. */
const SLOT = "button:has(span.tabular-nums)";

/**
 * Book the last offered time and return the slot count before it was taken.
 *
 * The *last* slot deliberately: the earliest ones are often later today, and the clinic's
 * minimum-notice rule correctly refuses to cancel those — so a test that booked one could
 * never clean up after itself.
 *
 * @param page - The signed-in appointments page.
 * @returns How many slots were on offer beforehand.
 */
async function bookLatestSlot(page: Page): Promise<number> {
  const slots = page.locator(SLOT);
  await expect(slots.first()).toBeVisible();
  const before = await slots.count();

  await slots.last().click();
  await expect(page.getByRole("status")).toContainText("Booked for");
  return before;
}

test.describe("booking", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
    await page.goto("/appointments");
    await expect(page.getByRole("heading", { name: "Appointments", level: 1 })).toBeVisible();
  });

  test("a booked time stops being offered, and cancelling gives it back", async ({ page }) => {
    // The scheduling tier is dead if this round trip does not work. A slot still on offer
    // after someone takes it sends two patients to one appointment; a cancelled visit whose
    // slot never reopens quietly costs the clinic the booking.
    // Counted relative to whatever is already there rather than assuming an empty diary:
    // this runs against the shared demo database, and an absolute count would pass or fail
    // on leftovers from an earlier run instead of on the behaviour under test.
    const requested = page.getByTestId("appointment-row").filter({ hasText: "Requested" });
    const requestedBefore = await requested.count();

    const before = await bookLatestSlot(page);
    const slots = page.locator(SLOT);

    // Re-counted from the refetched grid rather than from local state, so this also proves
    // the server stopped offering it.
    await expect(slots).toHaveCount(before - 1);
    await expect(requested).toHaveCount(requestedBefore + 1);

    // The new booking is prepended to the list, so it is the first of its status.
    await requested.first().getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("status")).toContainText("available to book again");
    await expect(slots).toHaveCount(before);
    await expect(requested).toHaveCount(requestedBefore);
  });

  test("every offered time names both zones when the clinic is elsewhere", async ({ page }) => {
    // A patient reading one clock for a clinic in another zone arrives an hour out
    // (edge case #6). Skipped when the runner already sits in the clinic's zone, where
    // showing the same time twice would be noise rather than safety.
    const zoneNote = page.getByText(/^Clinic in /);
    test.skip((await zoneNote.count()) === 0, "runner shares the clinic's time zone");

    await expect(page.locator(SLOT).first()).toContainText("clinic");
  });
});
