import { expect, test } from "@playwright/test";

// The mobile shell (≤768px): the feeds sidebar is an off-canvas drawer opened
// from the top-bar hamburger; picking a feed switches streams and closes it.

test.describe("mobile shell", () => {
  test.use({ viewport: { width: 390, height: 780 } });

  test("feeds open in a drawer, navigate, and the drawer closes", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("[data-index]");

    // No inline sidebar on mobile — open it from the hamburger.
    await page.getByRole("button", { name: "Open feeds" }).click();
    const drawer = page.getByRole("dialog");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("link", { name: /All items/ })).toBeVisible();

    // Tapping a feed switches the stream and dismisses the drawer.
    await drawer.getByRole("link", { name: /Nature/ }).click();
    await expect(page.getByRole("heading", { name: "Nature", level: 1 })).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
});
