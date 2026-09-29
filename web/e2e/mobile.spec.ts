import { expect, test } from "@playwright/test";

import { resetSeedData } from "./reset";

// The mobile shell (≤768px): the feeds sidebar is an off-canvas drawer opened
// from the top-bar hamburger; picking a feed switches streams and closes it.

test.beforeAll(resetSeedData);

test.describe("mobile shell", () => {
  test.use({ viewport: { width: 390, height: 780 } });

  test("feeds open in a drawer, navigate, and the drawer closes", async ({ page }) => {
    await page.goto("/app/");
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

  test("the actions menu loads on first tap and works", async ({ page }) => {
    const menuChunk: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("MobileActionsMenu")) menuChunk.push(r.url());
    });
    await page.goto("/app/");
    await page.waitForSelector("[data-index]");
    // Not fetched at startup: the header shows a look-alike button until the tap.
    expect(menuChunk).toHaveLength(0);

    await page.getByRole("button", { name: "More actions" }).click();
    const menu = page.getByRole("menu");
    await expect(menu).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: /Refresh/ })).toBeVisible();

    await menu.getByRole("menuitemradio", { name: /Dark/ }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.getByRole("menu")).toHaveCount(0);

    // Once loaded it is the real Radix trigger: reopen, Esc closes, focus returns.
    await page.getByRole("button", { name: "More actions" }).click();
    await expect(page.getByRole("menu")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "More actions" })).toBeFocused();
  });

  test("the actions menu works from the keyboard on the first open", async ({ page }) => {
    await page.goto("/app/");
    await page.waitForSelector("[data-index]");
    // The first press hits the look-alike button, which loads the menu and mounts it
    // open. Keyboard users must land inside the menu, not on a button that vanished.
    await page.getByRole("button", { name: "More actions" }).focus();
    await page.keyboard.press("Enter");
    const menu = page.getByRole("menu");
    await expect(menu).toBeVisible();
    // Same as a keyboard open of the real Radix trigger: the first item has focus.
    await expect(menu.getByRole("menuitem", { name: /Refresh/ })).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(menu.getByRole("menuitem", { name: /Mark all read/ })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).toHaveCount(0);
  });

  test("Refresh from the menu refetches the stream", async ({ page }) => {
    await page.goto("/app/");
    await page.waitForSelector("[data-index]");
    await page.getByRole("button", { name: "More actions" }).click();
    const refetch = page.waitForRequest((r) => r.url().includes("/api/v1/streams/"));
    await page.getByRole("menuitem", { name: /Refresh/ }).click();
    await refetch;
    await expect(page.getByRole("menu")).toHaveCount(0);
  });

  test("Mark all read from the menu asks first, and Cancel changes nothing", async ({
    page,
  }) => {
    // Cancelled on purpose: the e2e specs share one database, and readstate.spec
    // runs after this file and counts unread entries.
    await page.goto("/app/");
    await page.waitForSelector("[data-index]");
    const unreadBefore = await page.locator("[data-index]").count();
    let marked = false;
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().includes("/mark-read")) marked = true;
    });

    await page.getByRole("button", { name: "More actions" }).click();
    await page.getByRole("menuitem", { name: /Mark all read/ }).click();
    const confirm = page.getByRole("dialog", { name: "Mark all as read?" });
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(confirm).toHaveCount(0);

    expect(marked).toBe(false);
    expect(await page.locator("[data-index]").count()).toBe(unreadBefore);
  });
});

test.describe("desktop shell", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("uses the inline actions and never loads the mobile menu", async ({ page }) => {
    const menuChunk: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("MobileActionsMenu")) menuChunk.push(r.url());
    });
    await page.goto("/app/");
    await page.waitForSelector("[data-index]");
    await expect(page.getByRole("button", { name: "More actions" })).toHaveCount(0);
    expect(menuChunk).toHaveLength(0);
  });
});
