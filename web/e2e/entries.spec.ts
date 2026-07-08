import { expect, test } from "@playwright/test";

// Drives the entry list + reading pane against the seed_dev dataset (~5k
// entries, with an XSS-probe entry as the newest item of the first feed).

test.describe("entry list + reading pane", () => {
  test("lists entries and opens an article into the reader", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("button[data-index]");

    // Open a normal article (row 0 is the XSS probe; open row 1).
    await page.locator("button[data-index='1']").click();
    const article = page.locator("article");
    await expect(article.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(article.getByText(/seeded article body/i)).toBeVisible();
  });

  test("virtualizes 5k entries and pages in on scroll", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("button[data-index]");
    const rows = page.locator("button[data-index]");
    const scroller = page.getByTestId("entry-scroll");

    // Scrolling to the tail repeatedly pages in deeper entries.
    for (let i = 0; i < 10; i++) {
      await scroller.evaluate((el) => el.scrollTo(0, el.scrollHeight));
      await page.waitForTimeout(150);
    }
    await page.waitForTimeout(500); // let the virtualizer settle

    const maxIndex = await rows.evaluateAll((els) =>
      Math.max(...els.map((e) => Number(e.getAttribute("data-index")))),
    );
    expect(maxIndex).toBeGreaterThan(100); // infinite pagination reached deep entries
    // A bounded window is in the DOM — nowhere near all 5000 nodes.
    expect(await rows.count()).toBeLessThan(800);
  });

  test("renders a hostile entry inert (sanitized)", async ({ page }) => {
    const dialogs: string[] = [];
    page.on("dialog", (d) => {
      dialogs.push(d.message());
      void d.dismiss();
    });

    await page.goto("/");
    await page.waitForSelector("button[data-index]");
    await page.getByRole("button", { name: /XSS probe/ }).click();

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
    await page.waitForSelector("button[data-index]");

    await page.locator("button[data-index='1']").click();
    const back = page.getByRole("button", { name: "Back" });
    await expect(back).toBeVisible();
    await expect(page.locator("article h1")).toBeVisible();

    await back.click();
    await expect(page.locator("button[data-index]").first()).toBeVisible();
    await expect(back).toBeHidden();
  });
});
