import { expect, test, type Page } from "@playwright/test";

// Read-state interactions (WP-11) against the seeded stack. Tests run serially
// (playwright.config workers:1) and share cumulative backend state, so they use
// delta assertions and put the destructive feed mark-all-read near the end.

async function totalUnread(page: Page): Promise<number> {
  const link = page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: /All items/ });
  const text = (await link.textContent()) ?? "";
  const m = text.match(/(\d+)/);
  return m ? Number(m[1]) : 0;
}

test.describe("read-state", () => {
  test("opening an entry marks it read and drops the unread count", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("button[data-index]");
    const before = await totalUnread(page);
    expect(before).toBeGreaterThan(0);

    await page.locator("button[data-index]:not([data-read])").first().click();
    await expect.poll(() => totalUnread(page)).toBeLessThan(before);
  });

  test("scroll-past marks entries read in one batched request", async ({ page }) => {
    const batchSizes: number[] = [];
    await page.route("**/api/v1/entries/state", async (route) => {
      const body = route.request().postDataJSON() as { ids?: number[] };
      batchSizes.push(body?.ids?.length ?? 0);
      await route.continue();
    });

    await page.goto("/");
    await page.waitForSelector("button[data-index]");
    // A feed with plenty of unread entries, untouched by the other tests.
    await page.getByRole("link", { name: /Nature/ }).click();
    await expect(page.getByRole("heading", { name: "Nature", level: 1 })).toBeVisible();

    const scroller = page.getByTestId("entry-scroll");
    for (let i = 0; i < 24; i++) {
      await scroller.evaluate((el) => el.scrollBy(0, 500));
      await page.waitForTimeout(60);
    }
    await page.waitForTimeout(1000); // let the 600ms settle fire and flush

    // A single request carried many ids (batched, not one-per-row).
    expect(Math.max(0, ...batchSizes)).toBeGreaterThan(1);
  });

  test("rolls back and toasts when the API fails mid-mark", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("button[data-index]");
    const before = await totalUnread(page);

    await page.route("**/api/v1/entries/state", (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "internal", message: "boom" } }),
      }),
    );

    await page.locator("button[data-index]:not([data-read])").first().click();
    await expect(page.getByRole("alert")).toContainText(/rolled back/i);
    // Optimistic drop is reverted.
    await expect.poll(() => totalUnread(page)).toBe(before);
  });

  test("star toggles and persists across reload", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("button[data-index]");
    await page.locator("button[data-index]").first().click();
    await page.waitForSelector("article h1");

    const star = page.getByRole("button", { name: /^Star/ });
    const wasPressed = (await star.getAttribute("aria-pressed")) === "true";
    await star.click();
    await expect(star).toHaveAttribute("aria-pressed", String(!wasPressed));

    await page.reload();
    await page.waitForSelector("button[data-index]");
    await page.locator("button[data-index]").first().click();
    await page.waitForSelector("article h1");
    await expect(page.getByRole("button", { name: /^Star/ })).toHaveAttribute(
      "aria-pressed",
      String(!wasPressed),
    );
  });

  test("mark-all-read clears a feed's unread count", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("button[data-index]");

    const feed = page.getByRole("link", { name: /The Verge/ });
    await feed.click();
    await expect(page.getByRole("heading", { name: "The Verge", level: 1 })).toBeVisible();

    await page.getByRole("button", { name: "Mark all read" }).click();
    // The feed's sidebar badge disappears (unread → 0).
    await expect.poll(async () => (await feed.textContent()) ?? "").not.toMatch(/\d/);
  });
});
