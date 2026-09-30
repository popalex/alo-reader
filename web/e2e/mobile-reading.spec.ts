import { expect, test, type Page } from "@playwright/test";

import { resetSeedData } from "./reset";

// On a phone the list and the reader take turns on one screen. Coming back from an
// article must land where the reader left the list. It used to jump about 15 rows
// down (the hidden list measured its rows at 0 px, and the virtualizer shifted the
// scroll position when they came back), and the scroll-read marker then marked the
// rows it had skipped as read: articles nobody saw.

test.beforeAll(resetSeedData);
test.use({ viewport: { width: 390, height: 844 } });

const scrollTop = (page: Page) =>
  page.getByTestId("entry-scroll").evaluate((el) => Math.round(el.scrollTop));
const totalUnread = async (page: Page) =>
  ((await (await page.request.get("/api/v1/counts")).json()) as { total_unread: number }).total_unread;

async function readOneAndComeBack(page: Page, scrolledTo: number): Promise<void> {
  await page.goto("/app/");
  await page.locator("[data-index]").first().waitFor();
  if (scrolledTo > 0) {
    await page.getByTestId("entry-scroll").evaluate((el, top) => el.scrollTo({ top }), scrolledTo);
  }
  await page.waitForTimeout(1500); // let the scroll-read marker settle first
  const place = await scrollTop(page);
  const unread = await totalUnread(page);

  // Open the second row fully in view, then come back.
  const rows = page.locator("[data-index]");
  let target = 0;
  for (let i = 0; i < (await rows.count()); i++) {
    const box = await rows.nth(i).boundingBox();
    if (box && box.y > 150) {
      target = i + 1;
      break;
    }
  }
  await rows.nth(target).click();
  const back = page.getByRole("button", { name: /back/i });
  await expect(back).toBeVisible();
  await back.click();
  await expect(page.locator("[data-index]").first()).toBeVisible();
  await page.waitForTimeout(1500); // longer than the read marker's settle time

  expect(Math.abs((await scrollTop(page)) - place)).toBeLessThanOrEqual(2);
  // Only the article that was opened may have changed state.
  expect(unread - (await totalUnread(page))).toBeLessThanOrEqual(1);
}

test("Back from the first screen of the list keeps the place and marks nothing else", async ({
  page,
}) => {
  await readOneAndComeBack(page, 0);
});

test("Back from further down the list keeps the place and marks nothing else", async ({ page }) => {
  await readOneAndComeBack(page, 2000);
});
