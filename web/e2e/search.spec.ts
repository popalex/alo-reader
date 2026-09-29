import { expect, test } from "@playwright/test";

import { resetSeedData } from "./reset";

// WP-13: `/` focuses search, typing filters the stream with highlighted snippets,
// Esc clears. Read-only against the seeded corpus (seed_dev bodies contain the
// word "paragraph"), so order among the serial specs doesn't matter.

test.beforeAll(resetSeedData);

test.describe("search", () => {
  test("/ focuses search, results are highlighted, Esc clears", async ({ page }) => {
    await page.goto("/app/");
    await page.waitForSelector("[data-index]");

    // `/` focuses the search box (WP-12 wired the shortcut; WP-13 makes it live).
    await page.keyboard.press("/");
    const box = page.getByRole("searchbox", { name: "Search articles" });
    await expect(box).toBeFocused();

    // Typing a term present in the seed bodies yields highlighted snippets.
    await box.fill("paragraph");
    await expect(page.locator("[data-index] b").first()).toBeVisible();
    const highlight = page.locator("[data-index] b").first();
    await expect(highlight).toHaveText(/paragraph/i);

    // Esc clears the query and returns to the normal listing (no highlights).
    await box.press("Escape");
    await expect(box).toHaveValue("");
    await expect(page.locator("[data-index] b")).toHaveCount(0);
  });

  test("scope toggle widens a feed search to all streams", async ({ page }) => {
    await page.goto("/app/");
    await page.waitForSelector("[data-index]");

    // Into a single feed, then search — scoped to that feed by default.
    await page.getByRole("link", { name: /Nature/ }).click();
    await expect(page.getByRole("heading", { name: "Nature", level: 1 })).toBeVisible();

    await page.keyboard.press("/");
    await page.getByRole("searchbox", { name: "Search articles" }).fill("paragraph");
    await expect(page.locator("[data-index] b").first()).toBeVisible();

    // Assert on what the rows are, not how many are on screen. The list is
    // virtualized, so the DOM holds only the rows that fit, and "All" rows (longer
    // feed names and snippets) can fit fewer: comparing rendered counts failed in CI
    // with 19 scoped rows and 17 unscoped ones. Every row shows its feed's title.
    const rowTexts = () => page.locator("[data-index]").allInnerTexts();
    const scoped = await rowTexts();
    expect(scoped.length).toBeGreaterThan(0);
    expect(scoped.every((text) => text.includes("Nature"))).toBe(true);

    // Switch scope to "All": every subscription is searched, so other feeds appear.
    await page.getByRole("button", { name: "All", exact: true }).click();
    await expect(page.locator("[data-index] b").first()).toBeVisible();
    await expect
      .poll(async () => (await rowTexts()).some((text) => !text.includes("Nature")))
      .toBe(true);
  });
});
