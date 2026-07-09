import { expect, test } from "@playwright/test";

// WP-13: `/` focuses search, typing filters the stream with highlighted snippets,
// Esc clears. Read-only against the seeded corpus (seed_dev bodies contain the
// word "paragraph"), so order among the serial specs doesn't matter.

test.describe("search", () => {
  test("/ focuses search, results are highlighted, Esc clears", async ({ page }) => {
    await page.goto("/");
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
    await page.goto("/");
    await page.waitForSelector("[data-index]");

    // Into a single feed, then search — scoped to that feed by default.
    await page.getByRole("link", { name: /Nature/ }).click();
    await expect(page.getByRole("heading", { name: "Nature", level: 1 })).toBeVisible();

    await page.keyboard.press("/");
    await page.getByRole("searchbox", { name: "Search articles" }).fill("paragraph");
    await expect(page.locator("[data-index] b").first()).toBeVisible();
    const scoped = await page.locator("[data-index]").count();

    // Switch scope to "All" — searches every subscription, so at least as many hits.
    await page.getByRole("button", { name: "All", exact: true }).click();
    await expect(page.locator("[data-index] b").first()).toBeVisible();
    await expect.poll(() => page.locator("[data-index]").count()).toBeGreaterThanOrEqual(scoped);
  });
});
