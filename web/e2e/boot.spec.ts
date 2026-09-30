import { expect, test } from "@playwright/test";

import { resetSeedData } from "./reset";

// Runs against the real stack seeded by scripts/seed_dev.py (folders + 20 feeds
// + ~5k entries). AUTH_MODE=none, so the SPA's bare requests resolve to the
// single seeded user.

test.beforeAll(resetSeedData);

test.describe("app boot (AUTH_MODE=none)", () => {
  test("boots to the three-pane app with live sidebar data", async ({ page }) => {
    await page.goto("/app/");

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
    await page.goto("/app/");
    await page.getByRole("link", { name: /Hacker News/ }).click();
    await expect(page).toHaveURL(/\/feed\/\d+$/);
    await expect(page.getByRole("heading", { name: "Hacker News", level: 1 })).toBeVisible();
  });
});

test("a self-hosted instance keeps out of search results", async ({ request }) => {
  // AUTH_MODE=none is a private reader, even when it is reachable from the internet.
  const robots = await request.get("/robots.txt");
  expect(await robots.text()).toContain("Disallow: /");
  for (const path of ["/app/", "/api/v1/config"]) {
    expect((await request.get(path)).headers()["x-robots-tag"], path).toBe("noindex, nofollow");
  }
  // The landing page and the moving guides belong to clerk mode only.
  for (const path of ["/landing.html", "/from/feedly", "/from/feedly.html"]) {
    expect((await request.get(path, { maxRedirects: 0 })).status(), path).toBe(404);
  }
});

test("unknown addresses: a 404 page outside the app, a not-found screen inside it", async ({
  page,
  request,
}) => {
  // Outside the app: the error page, with a real 404 and the self-host wording.
  for (const path of ["/some-old-link", "/from/feedly", "/error.html"]) {
    const r = await request.get(path, { maxRedirects: 0 });
    expect(r.status(), path).toBe(404);
    const html = await r.text();
    expect(html, path).toContain("This page is not here.");
    expect(html, path).toContain("Open Alo Reader");
    expect(html, path).not.toContain("Create an account");
    expect(html, path).not.toContain("{{");
  }
  // Code reads these, so they stay bare.
  const api = await request.get("/api/v1/nope");
  expect(api.status()).toBe(404);
  expect(api.headers()["content-type"]).toContain("application/json");
  const chunk = await request.get("/app/assets/missing.js");
  expect(chunk.status()).toBe(404);
  expect(await chunk.text()).not.toContain("This page is not here.");

  // Inside the app: the sidebar stays, the list pane says so, and the way out works.
  await page.goto("/app/no-such-page");
  await expect(page.getByRole("heading", { name: "Nothing here.", level: 1 })).toBeVisible();
  await page.getByRole("link", { name: "Go to All items" }).click();
  await expect(page).toHaveURL(/\/app\/$/);
  await expect(page.getByRole("heading", { name: "All items", level: 1 })).toBeVisible();
});
