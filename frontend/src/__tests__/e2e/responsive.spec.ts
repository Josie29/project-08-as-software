import { expect, test } from "@playwright/test";

import {
  PHONE,
  SCREENS,
  expectNoHorizontalScroll,
  expectTappableControls,
  signIn,
} from "./support";

test.use({ viewport: PHONE });

test.describe(`every screen at ${PHONE.width}px`, () => {
  test("the sign-in and identity screens fit", async ({ page }) => {
    for (const path of ["/login", "/verify"]) {
      await page.goto(path);
      await expectNoHorizontalScroll(page, path);
      await expectTappableControls(page, path);
    }
  });

  test.describe("signed in", () => {
    test.beforeEach(async ({ page }) => {
      await signIn(page);
    });

    for (const { path, heading } of SCREENS) {
      test(`${path} fits and is tappable`, async ({ page }) => {
        await page.goto(path);
        await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
        await expectNoHorizontalScroll(page, path);
        await expectTappableControls(page, path);
      });
    }

    test("the navigation rail stacks above the content instead of squeezing beside it", async ({
      page,
    }) => {
      await page.goto("/studies");
      const rail = page.getByRole("navigation", { name: "Portal sections" });
      const main = page.getByRole("main");
      const railBox = await rail.boundingBox();
      const mainBox = await main.boundingBox();
      expect(railBox && mainBox).toBeTruthy();
      // Stacked, not side by side: two columns at this width leaves neither usable.
      expect(mainBox!.y).toBeGreaterThan(railBox!.y);
      expect(railBox!.width).toBeGreaterThan(PHONE.width * 0.7);
    });

    test("thumbnails lay out in more than one column on a phone", async ({ page }) => {
      await page.goto("/studies");
      const thumbs = page.getByRole("button", { name: /IMG-\d{4}/ });
      await expect(thumbs.first()).toBeVisible();
      const tops = await thumbs.evaluateAll((els) =>
        els.map((el) => Math.round(el.getBoundingClientRect().top)),
      );
      // One column turns eleven images into a page thousands of pixels tall, which is a
      // scroll marathon rather than a gallery.
      expect(new Set(tops).size).toBeLessThan(tops.length);
    });

    test("the image viewer keeps its controls on screen and does not overflow", async ({
      page,
    }) => {
      await page.goto("/studies");
      await page
        .getByRole("button", { name: /IMG-0001/ })
        .first()
        .click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();

      await expectNoHorizontalScroll(page, "image viewer");
      // The Share control sits at the bottom of the dialog; if the dialog is taller than the
      // viewport it is the first thing to fall off the screen.
      const share = dialog.getByRole("button", { name: "Share" });
      const box = await share.boundingBox();
      expect(box).toBeTruthy();
      expect(box!.y + box!.height).toBeLessThanOrEqual(PHONE.height);
    });

    test("the cine transport stays reachable on a phone", async ({ page }) => {
      await page.goto("/studies");
      await page.getByRole("button", { name: /100 frames/ }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();

      await expectNoHorizontalScroll(page, "cine player");
      const scrub = dialog.getByRole("slider", { name: /frame/i });
      const box = await scrub.boundingBox();
      expect(box).toBeTruthy();
      expect(box!.y + box!.height).toBeLessThanOrEqual(PHONE.height);
      expect(box!.height).toBeGreaterThanOrEqual(28);
    });

    test("the access log scrolls inside its own container, not the page", async ({ page }) => {
      await page.goto("/activity");
      await expectNoHorizontalScroll(page, "/activity");
      // The table is wider than a phone by design; the fix is a scroll container around it,
      // not a table that squeezes its columns into illegibility.
      const scroller = page.locator("div.overflow-x-auto").first();
      const scrolls = await scroller.evaluate((el) => el.scrollWidth > el.clientWidth);
      expect(scrolls).toBe(true);
    });
  });
});
