import { expect, test } from "@playwright/test";

// Drives the entry list + reading pane against the seed_dev dataset (~5k
// entries, with an XSS-probe entry as the newest item of the first feed).

test.describe("entry list + reading pane", () => {
  test("lists entries and opens an article into the reader", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("[data-index]");

    // Open a normal article (row 0 is the XSS probe; open row 1).
    await page.locator("[data-index='1']").click();
    const article = page.locator("article");
    await expect(article.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(article.getByText(/seeded article body/i)).toBeVisible();
  });

  test("virtualizes 5k entries and pages in on scroll", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("[data-index]");
    const rows = page.locator("[data-index]");
    const scroller = page.getByTestId("entry-scroll");

    // Scroll gently (as a user would); the tail pages in as we go.
    for (let i = 0; i < 40; i++) {
      await scroller.evaluate((el) => el.scrollBy(0, 500));
      await page.waitForTimeout(60);
    }
    await page.waitForTimeout(300);

    const maxIndex = await rows.evaluateAll((els) =>
      Math.max(...els.map((e) => Number(e.getAttribute("data-index")))),
    );
    expect(maxIndex).toBeGreaterThan(60); // infinite pagination reached deep entries
    // Only a bounded window is in the DOM — nowhere near all 5000 nodes.
    expect(await rows.count()).toBeLessThan(120);
  });

  test("renders a hostile entry inert (sanitized)", async ({ page }) => {
    const dialogs: string[] = [];
    page.on("dialog", (d) => {
      dialogs.push(d.message());
      void d.dismiss();
    });

    await page.goto("/");
    await page.waitForSelector("[data-index]");
    await page.locator("[data-index='0']").click(); // row 0 is the XSS probe

    const article = page.locator("article");
    await expect(article.getByRole("heading", { name: /XSS probe/ })).toBeVisible();
    await expect(article.getByText("Safe intro paragraph")).toBeVisible();

    expect(dialogs).toHaveLength(0);
    expect(await page.locator("article script").count()).toBe(0);
    const fired = await page.evaluate(() => (window as unknown as { __xss_fired?: boolean }).__xss_fired);
    expect(fired ?? false).toBeFalsy();
  });
});

test.describe("mobile", () => {
  test.use({ viewport: { width: 390, height: 780 } });

  test("list -> entry -> back", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("[data-index]");

    await page.locator("[data-index='1']").click();
    const back = page.getByRole("button", { name: "Back" });
    await expect(back).toBeVisible();
    await expect(page.locator("article h1")).toBeVisible();

    await back.click();
    await expect(page.locator("[data-index]").first()).toBeVisible();
    await expect(back).toBeHidden();
  });
});
