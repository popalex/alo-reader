import { expect, test } from "@playwright/test";

// WP-14 acceptance: the PWA keeps working with the network off. Each Playwright
// test gets its own context (fresh service worker + caches), so these don't leak
// SW state into the other specs.

test.describe("offline / PWA", () => {
  test("opening an uncached article offline shows a calm notice, not an error toast", async ({
    page,
    context,
  }) => {
    await page.goto("/");
    await page.waitForSelector("[data-index]");
    await context.setOffline(true);
    await expect(page.getByTestId("offline-bar")).toBeVisible();

    // An article whose detail was never fetched can't load offline.
    await page.locator("[data-index='2']").click();
    await expect(page.locator("article")).toContainText(/offline/i);
    // …and no alarming generic error toast.
    await expect(page.getByText(/Something went wrong/)).toHaveCount(0);
  });

  test("queues read changes offline and replays them exactly once on reconnect", async ({
    page,
    context,
  }) => {
    const statePosts: string[] = [];
    page.on("request", (req) => {
      if (req.method() === "POST" && req.url().includes("/api/v1/entries/state")) {
        statePosts.push(req.url());
      }
    });
    await page.goto("/");
    await page.waitForSelector("[data-index]");

    // Go offline; the status bar confirms it.
    await context.setOffline(true);
    await expect(page.getByTestId("offline-bar")).toBeVisible();

    // Star five distinct entries by keyboard (j = next, s = toggle star). A star
    // always mutates, so this is a clean "five changes made offline".
    for (let i = 0; i < 5; i++) {
      await page.keyboard.press("j");
      await page.keyboard.press("s");
    }

    // Badge shows the five queued changes; nothing was sent while offline.
    await expect(page.getByTestId("queued-count")).toHaveText("5");
    expect(statePosts).toHaveLength(0);

    // Reconnect → the queue drains: exactly five POSTs, then the bar disappears.
    await context.setOffline(false);
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect(page.getByTestId("offline-bar")).toHaveCount(0, { timeout: 15000 });
    expect(statePosts).toHaveLength(5);
  });

  test("hard-reload while offline still boots the app shell", async ({ page, context }) => {
    // First visit registers + activates the service worker.
    await page.goto("/");
    await page.waitForFunction(() => navigator.serviceWorker?.controller != null, null, {
      timeout: 20_000,
    });
    // An online reload under SW control warms the shell-data caches (/config etc.).
    await page.reload();
    await page.waitForSelector("[data-index]");

    // Now offline: a hard reload must still boot the three-pane shell from cache,
    // not the "Could not start" boot error.
    await context.setOffline(true);
    await page.reload();
    await expect(page.getByRole("heading", { name: "All items", level: 1 })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Views" })).toBeVisible();
  });

  test("is installable: manifest + active service worker", async ({ page }) => {
    await page.goto("/");
    await page.waitForFunction(() => navigator.serviceWorker?.controller != null, null, {
      timeout: 20_000,
    });

    const href = await page.getAttribute('link[rel="manifest"]', "href");
    expect(href).toBeTruthy();
    const manifest = await (
      await page.request.get(new URL(href!, page.url()).toString())
    ).json();

    expect(manifest.name).toBeTruthy();
    expect(manifest.display).toBe("standalone");
    const sizes: string[] = manifest.icons.map((i: { sizes: string }) => i.sizes);
    expect(sizes).toContain("192x192");
    expect(sizes).toContain("512x512");
    expect(manifest.icons.some((i: { purpose?: string }) => i.purpose === "maskable")).toBe(true);
  });
});
