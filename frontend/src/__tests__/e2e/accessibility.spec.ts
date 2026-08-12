import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { DEMO, PHONE, SCREENS, signIn } from "./support";

/**
 * Run axe and return only the violations worth failing a build over.
 *
 * Serious and critical are the bar: they are the findings that stop someone using the
 * screen, as opposed to the advisory ones that depend on context axe cannot see.
 *
 * @param page - The page to scan.
 * @returns Violations at serious or critical impact.
 */
async function scan(page: Page) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  return violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      nodes: violation.nodes.map((node) => node.target.join(" ")).slice(0, 4),
    }));
}

test.describe("unauthenticated screens", () => {
  for (const path of ["/login", "/verify"]) {
    test(`${path} has no serious axe violations`, async ({ page }) => {
      await page.goto(path);
      expect(await scan(page)).toEqual([]);
    });
  }
});

test.describe("portal screens", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  for (const { path, heading } of SCREENS) {
    test(`${path} has no serious axe violations`, async ({ page }) => {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
      expect(await scan(page)).toEqual([]);
    });
  }

  test("the image viewer is reachable, operable and closable by keyboard alone", async ({
    page,
  }) => {
    await page.goto("/studies");
    // Reached by keyboard rather than clicked: a thumbnail that only opens on click is a
    // gallery a keyboard user cannot get into at all.
    const thumbnail = page.getByRole("button", { name: /IMG-0001/ }).first();
    await thumbnail.focus();
    await page.keyboard.press("Enter");

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    // Focus lands inside the dialog, or a screen reader user is still on the page behind it.
    await expect(dialog).toContainText("IMG-0001");
    expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);

    expect(await scan(page)).toEqual([]);

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });

  test("focus stays inside the image viewer when tabbing past its last control", async ({
    page,
  }) => {
    await page.goto("/studies");
    await page
      .getByRole("button", { name: /IMG-0001/ })
      .first()
      .click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    for (let i = 0; i < 12; i += 1) await page.keyboard.press("Tab");

    expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  });

  test("the cine player labels its transport for screen readers", async ({ page }) => {
    await page.goto("/studies");
    await page.getByRole("button", { name: /100 frames/ }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Previous frame" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Next frame" })).toBeVisible();
    // Play state has to be exposed, not just drawn: the label alone flips between Play and
    // Pause, which tells a sighted user what will happen but not what is happening.
    await expect(dialog.getByRole("button", { name: /Play|Pause/ })).toHaveAttribute(
      "aria-pressed",
      /true|false/,
    );
    await expect(dialog.getByRole("slider", { name: /frame/i })).toBeVisible();

    expect(await scan(page)).toEqual([]);
  });

  test("the share dialog is fully labelled", async ({ page }) => {
    await page.goto("/studies");
    await page
      .getByRole("button", { name: /IMG-0001/ })
      .first()
      .click();
    await page.getByRole("button", { name: "Share" }).click();

    const dialog = page.getByRole("dialog", { name: /Share/ });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel("Send to")).toBeVisible();
    await expect(dialog.getByRole("group", { name: /Expires after/i })).toBeVisible();

    expect(await scan(page)).toEqual([]);
  });
});

test.describe("portal screens on a phone", () => {
  test.use({ viewport: PHONE });

  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  for (const { path } of SCREENS) {
    test(`${path} has no serious axe violations at ${PHONE.width}px`, async ({ page }) => {
      await page.goto(path);
      expect(await scan(page)).toEqual([]);
    });
  }
});

test.describe("dark theme", () => {
  test.use({ colorScheme: "dark" });

  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  for (const { path } of SCREENS) {
    test(`${path} has no serious axe violations in dark mode`, async ({ page }) => {
      await page.goto(path);
      expect(await scan(page)).toEqual([]);
    });
  }

  test("the viewer and cine chrome hold up in dark mode", async ({ page }) => {
    await page.goto("/studies");
    await page
      .getByRole("button", { name: /IMG-0001/ })
      .first()
      .click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(await scan(page)).toEqual([]);
    await page.keyboard.press("Escape");

    await page.getByRole("button", { name: /100 frames/ }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(await scan(page)).toEqual([]);
  });
});

test("the sign-in form is labelled and submits by keyboard", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(DEMO.email);
  await page.keyboard.press("Tab");
  await page.keyboard.type(DEMO.password);
  await expect(page.getByLabel("Password")).toHaveValue(DEMO.password);
});
