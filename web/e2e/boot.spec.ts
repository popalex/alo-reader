import { expect, test } from "@playwright/test";

// Runs against the real stack seeded by scripts/e2e.sh: a "Tech" folder with a
// subscription to the fixture feed ("Smoke Test Feed"), polled so it has a
// title and unread entries. AUTH_MODE=none, so the SPA's bare requests resolve
// to the same single user the script seeded.

test.describe("app boot (AUTH_MODE=none)", () => {
  test("boots to the three-pane app with live sidebar data", async ({ page }) => {
    await page.goto("/");

    // Fixed views always render.
    const views = page.getByRole("navigation", { name: "Views" });
    await expect(views.getByText("All items")).toBeVisible();
    await expect(views.getByText("Starred")).toBeVisible();

    // Seeded folder + feed from the real API.
    await expect(page.getByText("Tech")).toBeVisible();
    await expect(page.getByRole("link", { name: /Smoke Test Feed/ })).toBeVisible();

    // Unread badge on All items (the worker ingested entries).
    await expect(views.getByText(/^\d+$/)).toBeVisible();

    // Both empty panes render (the list/reader arrive in WP-10).
    await expect(page.getByText("Nothing here yet")).toBeVisible();
    await expect(page.getByText("Select an article")).toBeVisible();
  });

  test("navigating to a feed updates the reading pane header", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /Smoke Test Feed/ }).click();
    await expect(page).toHaveURL(/\/feed\/\d+$/);
    await expect(page.getByRole("heading", { name: "Smoke Test Feed" })).toBeVisible();
  });

  test("theme toggle switches to dark mode", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("html")).not.toHaveAttribute("data-theme", "dark");
    await page.getByRole("button", { name: "Dark theme" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  });
});
