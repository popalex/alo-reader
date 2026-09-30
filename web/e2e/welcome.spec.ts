import { type APIRequestContext, expect, test } from "@playwright/test";

import { resetSeedData } from "./reset";

// A new account has no feeds: the list and reader panes give way to a welcome screen
// whose main action is importing an OPML file. The seeded user is emptied first, and
// the seed is put back afterwards for the next spec file.

async function unsubscribeAll(request: APIRequestContext): Promise<void> {
  const subs = (await (await request.get("/api/v1/subscriptions")).json()) as { id: number }[];
  for (const s of subs) {
    expect((await request.delete(`/api/v1/subscriptions/${s.id}`)).status()).toBe(204);
  }
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

  test("on a phone, both ways in and the drawer are on screen", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 780 });
    await page.goto("/app/");
    await expect(page.getByText("Import an OPML file")).toBeInViewport();
    await expect(page.getByRole("button", { name: "Add a feed" })).toBeVisible();
    await page.getByRole("button", { name: "Open feeds" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });
});
