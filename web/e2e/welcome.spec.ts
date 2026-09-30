import { type APIRequestContext, expect, test } from "@playwright/test";

import { resetSeedData } from "./reset";

// A new account has no feeds: the list and reader panes give way to a welcome screen
// whose main action is importing an OPML file. The seeded user is emptied first, and
// the seed is put back afterwards for the next spec file.

// The API rate-limits each user (RATE_LIMIT_RPS=10, RATE_LIMIT_BURST=30). Deleting the
// seeded 20 feeds in a burst spends most of that, and the test's own page load and
// subscribes then got 429s ("1 could not be added"). So a refused delete is retried,
// and after a big cleanup the bucket gets time to refill before the test starts.
async function unsubscribeAll(request: APIRequestContext): Promise<void> {
  const subs = (await (await request.get("/api/v1/subscriptions")).json()) as { id: number }[];
  for (const s of subs) {
    let status = 0;
    for (let attempt = 0; attempt < 5; attempt++) {
      status = (await request.delete(`/api/v1/subscriptions/${s.id}`)).status();
      if (status !== 429) break;
      await new Promise((r) => setTimeout(r, 1000));
    }
    expect(status).toBe(204);
  }
  if (subs.length > 5) await new Promise((r) => setTimeout(r, 3000));
}

const opml = `<?xml version="1.0" encoding="UTF-8"?>
<opml version="1.0">
  <body>
    <outline text="Welcome One" type="rss" xmlUrl="https://welcome-one.example/feed.xml"/>
    <outline text="Welcome Two" type="rss" xmlUrl="https://welcome-two.example/feed.xml"/>
  </body>
</opml>`;

test.beforeAll(resetSeedData);
test.afterAll(resetSeedData);

test.describe("welcome screen (an account with no feeds)", () => {
  test.beforeEach(async ({ request }) => unsubscribeAll(request));

  test("replaces the empty panes, and importing from it brings the reader back", async ({ page }) => {
    await page.goto("/app/");
    await expect(page.getByRole("heading", { name: "Welcome to alo reader", level: 1 })).toBeVisible();
    // No empty reader pane beside it.
    await expect(page.getByText("Select an article")).toHaveCount(0);

    await page
      .getByRole("region", { name: "Welcome" })
      .locator('input[type="file"]')
      .setInputFiles({ name: "feeds.opml", mimeType: "text/xml", buffer: Buffer.from(opml) });

    await expect(page.getByText("Imported 2 feeds.")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Welcome to alo reader" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "All items", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: /Welcome One/ })).toBeVisible();
  });

  test("Add a feed opens the add-feed dialog", async ({ page }) => {
    await page.goto("/app/");
    await page.getByRole("button", { name: "Add a feed" }).click();
    await expect(page.getByRole("heading", { name: "Add a feed" })).toBeVisible();
    await expect(page.getByLabel(/feed or site url/i)).toBeVisible();
  });

  test("ticking starter feeds and subscribing brings the reader back with them", async ({ page }) => {
    await page.goto("/app/");
    await expect(page.getByRole("button", { name: "Subscribe to ticked feeds" })).toBeDisabled();

    await page.getByLabel(/NASA Image of the Day/).check();
    await page.getByLabel(/Quanta Magazine/).check();
    await page.getByRole("button", { name: "Subscribe to 2 feeds" }).click();

    // Both are subscribed before the welcome screen gives way. Whether the feeds can
    // be fetched from here does not matter: the subscriptions exist either way.
    await expect(page.getByText("Subscribed to 2 feeds.")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Welcome to alo reader" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /NASA Image of the Day/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /Quanta Magazine/ })).toBeVisible();
  });

  test("on a phone, both ways in and the drawer are on screen", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 780 });
    await page.goto("/app/");
    await expect(page.getByText("Import an OPML file")).toBeInViewport();
    await expect(page.getByRole("button", { name: "Add a feed" })).toBeVisible();
    await page.getByRole("button", { name: "Open feeds" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });
});
