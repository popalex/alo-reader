import { expect, test, type Page } from "@playwright/test";

import { resetSeedData } from "./reset";

// A feed that fails to update says so above its list, and offers something to do
// about it. The seed's Reuters feed carries a fetch error.

test.beforeAll(resetSeedData);

async function openReuters(page: Page): Promise<void> {
  await page.goto("/app/");
  await page.getByRole("link", { name: /Reuters/ }).first().click();
  await expect(page.getByRole("alert").filter({ hasText: "This feed failed to update" })).toBeVisible();
}

test("the banner's Try again queues a fetch, and says so when it was just tried", async ({
  page,
}) => {
  await openReuters(page);
  const retry = page.getByRole("button", { name: "Try again" });
  const refreshed = page.waitForResponse((r) => /\/subscriptions\/\d+\/refresh$/.test(r.url()));
  await retry.click();
  expect((await refreshed).status()).toBe(202);
  await expect(page.getByText("Checking Reuters again.")).toBeVisible();

  // Within the cooldown the server refuses (429); the toast says what to do.
  await retry.click();
  await expect(page.getByText("This feed was checked moments ago. Try again in a minute.")).toBeVisible();
});

test("the banner's Feed settings opens that feed's settings", async ({ page }) => {
  await openReuters(page);
  await page.getByRole("button", { name: "Feed settings" }).click();
  await expect(page.getByRole("heading", { name: "Feed settings" })).toBeVisible();
  await expect(page.getByLabel(/^title$/i)).toHaveValue("Reuters");
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("Feed settings opens from the banner without the drawer", async ({ page }) => {
    await page.goto("/app/");
    await page.getByRole("button", { name: "Open feeds" }).click();
    await page.getByRole("dialog").getByRole("link", { name: /Reuters/ }).click();
    await expect(page.getByRole("alert").filter({ hasText: "This feed failed to update" })).toBeVisible();
    await page.getByRole("button", { name: "Feed settings" }).click();
    await expect(page.getByRole("heading", { name: "Feed settings" })).toBeVisible();
    await expect(page.getByLabel(/^title$/i)).toHaveValue("Reuters");
  });
});
