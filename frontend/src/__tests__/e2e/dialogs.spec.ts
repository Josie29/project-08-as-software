import { expect, test } from "@playwright/test";

import { signIn } from "./support";

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test("closing the share dialog leaves the image viewer open", async ({ page }) => {
  await page.goto("/studies");
  await page
    .getByRole("button", { name: /IMG-0001/ })
    .first()
    .click();
  const viewer = page.getByRole("dialog", { name: /Ultrasound image/ });
  await expect(viewer).toBeVisible();

  await page.getByRole("button", { name: "Share" }).click();
  const share = page.getByRole("dialog", { name: /Share/ });
  await expect(share).toBeVisible();

  // Escape dismisses the dialog on top, not the whole stack. Losing the viewer here means
  // a patient who changes their mind about sharing has to find their image again.
  await page.keyboard.press("Escape");
  await expect(share).toBeHidden();
  await expect(viewer).toBeVisible();
});

test("arrow keys do not change the image while the share dialog is open", async ({ page }) => {
  await page.goto("/studies");
  await page
    .getByRole("button", { name: /IMG-0001/ })
    .first()
    .click();
  const viewer = page.getByRole("dialog", { name: /Ultrasound image/ });
  await page.getByRole("button", { name: "Share" }).click();
  await expect(page.getByRole("dialog", { name: /Share/ })).toBeVisible();

  await page.keyboard.press("ArrowRight");

  // Sharing image 1 must not quietly become sharing image 2.
  await expect(viewer).toContainText("IMG-0001");
});

test("focus stays inside the share dialog", async ({ page }) => {
  await page.goto("/studies");
  await page
    .getByRole("button", { name: /IMG-0001/ })
    .first()
    .click();
  await page.getByRole("button", { name: "Share" }).click();
  const share = page.getByRole("dialog", { name: /Share/ });
  await expect(share).toBeVisible();

  for (let i = 0; i < 10; i += 1) await page.keyboard.press("Tab");

  expect(await share.evaluate((el) => el.contains(document.activeElement))).toBe(true);
});

test("closing a dialog returns focus to the control that opened it", async ({ page }) => {
  await page.goto("/studies");
  const thumbnail = page.getByRole("button", { name: /IMG-0001/ }).first();
  await thumbnail.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();

  // Without this a keyboard user is dropped at the top of the document and has to tab all
  // the way back to where they were.
  expect(await thumbnail.evaluate((el) => el === document.activeElement)).toBe(true);
});

test("space activates a focused button in the cine player instead of toggling playback", async ({
  page,
}) => {
  await page.goto("/studies");
  await page.getByRole("button", { name: /100 frames/ }).click();
  const player = page.getByRole("dialog");
  await expect(player).toBeVisible();

  const next = player.getByRole("button", { name: "Next frame" });
  await next.focus();
  await page.keyboard.press("Space");

  // The global Space shortcut must not swallow Space from a focused control — that makes
  // every button in the transport unusable by keyboard.
  await expect(player).toContainText("002 / 100");
});

test("the cine player does not autoplay when reduced motion is requested", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();
  await signIn(page);
  await page.goto("/studies");
  await page.getByRole("button", { name: /100 frames/ }).click();
  const player = page.getByRole("dialog");
  await expect(player).toBeVisible();
  // Wait for loading to finish rather than a fixed delay: asserting while frames are still
  // arriving would pass simply because playback had not been triggered yet.
  await expect(player.getByRole("status")).toBeHidden({ timeout: 60_000 });
  await page.waitForTimeout(1500);

  await expect(player).toContainText("FROZEN");
  await expect(player.getByRole("button", { name: "Play" })).toBeVisible();
  await context.close();
});
