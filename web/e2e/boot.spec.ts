import { expect, test } from "@playwright/test";

// Runs against the real stack seeded by scripts/seed_dev.py (folders + 20 feeds
// + ~5k entries). AUTH_MODE=none, so the SPA's bare requests resolve to the
// single seeded user.

test.describe("app boot (AUTH_MODE=none)", () => {
  test("boots to the three-pane app with live sidebar data", async ({ page }) => {
    await page.goto("/");

    // Fixed views + a seeded folder and feed.
    const views = page.getByRole("navigation", { name: "Views" });
    await expect(views.getByText("All items")).toBeVisible();
    await expect(views.getByText("Starred")).toBeVisible();
    // Folder labels are uppercased via CSS, so match case-insensitively.
    await expect(page.getByText(/^tech$/i)).toBeVisible();
    await expect(page.getByRole("link", { name: /Hacker News/ })).toBeVisible();

    // Unread badge on All items.
    await expect(views.getByText(/^\d+$/)).toBeVisible();

    // The reader starts empty until an entry is selected.
    await expect(page.getByText("Select an article")).toBeVisible();
  });

  test("navigating to a feed updates the list header", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /Hacker News/ }).click();
    await expect(page).toHaveURL(/\/feed\/\d+$/);
    await expect(page.getByRole("heading", { name: "Hacker News", level: 1 })).toBeVisible();
  });
});
