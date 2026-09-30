import { expect, test, type Page } from "@playwright/test";

import { resetSeedData } from "./reset";

// Reading on from one article to the next: j/k while an article is open, and the
// "Next article" button at the end of each article (the way on, on a phone).

test.beforeAll(resetSeedData);

const readerTitle = (page: Page) => page.locator("article h1");
const rowTitle = async (page: Page, index: number) =>
  (await page.locator(`[data-index="${index}"]`).textContent()) ?? "";
const totalUnread = async (page: Page) =>
  ((await (await page.request.get("/api/v1/counts")).json()) as { total_unread: number }).total_unread;

test("with an article open, j opens the next one and k the previous one", async ({ page }) => {
  await page.goto("/app/");
  await page.locator("[data-index]").first().click();
  const first = (await readerTitle(page).textContent()) ?? "";
  expect(await rowTitle(page, 0)).toContain(first);

  await page.keyboard.press("j");
  await expect(readerTitle(page)).not.toHaveText(first);
  expect(await rowTitle(page, 1)).toContain((await readerTitle(page).textContent()) ?? "");

  await page.keyboard.press("k");
  await expect(readerTitle(page)).toHaveText(first);
});

test("Next article at the end of an article opens the next one, at its top", async ({ page }) => {
  await page.goto("/app/");
  await page.locator("[data-index]").first().click();
  const second = await rowTitle(page, 1);
  const next = page.getByRole("button", { name: /next article/i });
  await next.scrollIntoViewIfNeeded();
  await next.click();
  await expect(readerTitle(page)).toBeVisible();
  expect(second).toContain((await readerTitle(page).textContent()) ?? "");
  expect(await page.locator("article").evaluate((el) => el.scrollTop)).toBe(0);
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("reading on with Next, then Back, lands on the last article read; nothing else is marked", async ({
    page,
  }) => {
    await page.goto("/app/");
    await page.locator("[data-index]").first().waitFor();
    await page.waitForTimeout(1000);
    const unread = await totalUnread(page);

    // Read on twelve articles, well past the first screenful of the list.
    await page.locator("[data-index]").first().click();
    for (let i = 0; i < 12; i++) {
      const before = (await readerTitle(page).textContent()) ?? "";
      await page.getByRole("button", { name: /next article/i }).click();
      await expect(readerTitle(page)).not.toHaveText(before);
    }
    const lastTitle = (await readerTitle(page).textContent()) ?? "";
    await page.getByRole("button", { name: /back/i }).click();

    // The list followed along: the last article read is on screen.
    const row = page.locator('[data-index="12"]');
    await expect(row).toBeInViewport({ ratio: 0.9 });
    expect((await row.textContent()) ?? "").toContain(lastTitle);
    await page.waitForTimeout(1500); // past the scroll-read marker's settle time
    // The thirteen articles opened, no more.
    expect(unread - (await totalUnread(page))).toBeLessThanOrEqual(13);
  });
});
