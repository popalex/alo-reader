import { expect, test } from "@playwright/test";

// Drives the feed-management UI added on wp-feed-management-ui against the real
// stack (AUTH_MODE=none). The discover→subscribe path needs a reachable feed
// server (unit-tested in tests/subscribe.test.tsx); OPML import creates the
// subscriptions straight from the uploaded file with no outbound fetch, so the
// whole flow — dialog → multipart upload → report → sidebar refresh — is
// exercised end to end here.

const OPML = `<?xml version="1.0" encoding="UTF-8"?>
<opml version="1.0">
  <body>
    <outline text="E2E Feed One" type="rss" xmlUrl="https://e2e-one.example/feed.xml"/>
    <outline text="E2E Feed Two" type="rss" xmlUrl="https://e2e-two.example/feed.xml"/>
  </body>
</opml>`;

test.describe("feed management (AUTH_MODE=none)", () => {
  test("subscribe button opens the add-feed dialog", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Subscribe", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Add a feed" })).toBeVisible();
    await expect(page.getByLabel(/feed or site url/i)).toBeVisible();
  });

  test("category: rename from the sidebar", async ({ page }) => {
    await page.goto("/");
    // The seeded "Tech" category — hover its header, rename it inline.
    const tech = page.getByRole("link", { name: /^tech$/i });
    await tech.hover();
    await page.getByRole("button", { name: /rename tech/i }).click();
    const input = page.getByRole("textbox", { name: /rename tech/i });
    await input.fill("Reading");
    await input.press("Enter");
    await expect(page.getByRole("link", { name: /^reading$/i })).toBeVisible();
  });

  test("mobile: the settings gear is visible without hover in the drawer", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 780 });
    await page.goto("/");
    await page.getByRole("button", { name: "Open feeds" }).click();
    const drawer = page.getByRole("dialog");
    // No hover on touch → the gear must be visible on its own (before any test
    // renames/deletes Hacker News).
    await expect(
      drawer.getByRole("button", { name: /settings for hacker news/i }),
    ).toBeVisible();
  });

  test("feed settings: rename a feed and see it update", async ({ page }) => {
    await page.goto("/");
    // Rename a feed the other tests don't touch (they use Hacker News).
    const feed = page.getByRole("link", { name: /The Verge/ });
    await feed.hover(); // reveal the hover-only gear (desktop)
    await page.getByRole("button", { name: /settings for the verge/i }).click();

    await expect(page.getByRole("heading", { name: "Feed settings" })).toBeVisible();
    await page.getByLabel(/^title$/i).fill("Verge Renamed");
    await page.getByRole("button", { name: /^save$/i }).click();

    await expect(page.getByRole("link", { name: /Verge Renamed/ })).toBeVisible();
  });

  test("deleting the feed you're viewing returns to All items", async ({ page }) => {
    await page.goto("/");
    // Open the feed's own stream (entries must load — guards the feed_id routing).
    await page.getByRole("link", { name: /Hacker News/ }).click();
    await expect(page).toHaveURL(/\/feed\/\d+$/);
    await expect(page.getByRole("heading", { name: "Hacker News", level: 1 })).toBeVisible();

    const feed = page.getByRole("link", { name: /Hacker News/ });
    await feed.hover(); // reveal the hover-only gear
    await page.getByRole("button", { name: /settings for hacker news/i }).click();
    await page.getByRole("button", { name: /delete feed/i }).click(); // inside the settings dialog
    await page.getByRole("button", { name: /^delete$/i }).click(); // confirm dialog

    await expect(page.getByRole("link", { name: /Hacker News/ })).toHaveCount(0);
    await expect(page).toHaveURL(/\/$/); // bounced back to All items, not left on the dead feed
  });

  test("imports an OPML file and the new feeds appear in the sidebar", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Subscribe", exact: true }).click();

    await page.locator('input[type="file"]').setInputFiles({
      name: "feeds.opml",
      mimeType: "text/xml",
      buffer: Buffer.from(OPML),
    });

    // The import report renders (2 imported), and the sidebar refreshes to list
    // the newly-created subscriptions (titles seeded from the OPML).
    await expect(page.getByText(/imported 2 · skipped 0/i)).toBeVisible();
    await page.getByRole("button", { name: /^done$/i }).click();
    await expect(page.getByRole("link", { name: /E2E Feed One/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /E2E Feed Two/ })).toBeVisible();
  });
});
