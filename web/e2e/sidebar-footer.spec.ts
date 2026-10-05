import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

import { resetSeedData } from "./reset";

// App-wide settings sit in the sidebar's footer: the theme, the feeds export, and the
// keyboard shortcut sheet (the way to find out the shortcuts exist). They used to be in the article
// list's toolbar (theme) or behind "?" only (shortcuts).

test.beforeAll(resetSeedData);

test("the theme switch is in the sidebar, and only there", async ({ page }) => {
  await page.goto("/app/");
  await page.locator("[data-index]").first().waitFor();
  await expect(page.getByRole("group", { name: "Colour theme" })).toHaveCount(1);
  const theme = page.locator("aside").getByRole("group", { name: "Colour theme" });
  await theme.getByRole("button", { name: "Dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("Keyboard shortcuts opens the sheet, and the list's keys wait while it is open", async ({
  page,
}) => {
  await page.goto("/app/");
  await page.locator("[data-index]").first().waitFor();
  await page.locator("aside").getByRole("button", { name: "Keyboard shortcuts" }).click();
  const sheet = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(sheet).toBeVisible();

  await page.keyboard.press("j"); // must not move the list behind the sheet
  await expect(page.locator("[data-index] :focus, [data-index]:focus")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
});

test("Export feeds downloads every subscription as one OPML file", async ({ page, request }) => {
  await page.goto("/app/");
  await page.locator("[data-index]").first().waitFor();
  const subs = (await (await request.get("/api/v1/subscriptions")).json()) as { feed_url: string }[];
  expect(subs.length).toBeGreaterThan(0);

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("aside").getByRole("button", { name: "Export feeds (OPML)" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^alo-reader-\d{4}-\d{2}-\d{2}\.opml$/);
  const opml = await readFile(await download.path(), "utf8");
  expect(opml).toContain("<title>Alo Reader subscriptions</title>");
  expect(opml.match(/<outline [^>]*xmlUrl=/g)).toHaveLength(subs.length);
  for (const { feed_url } of subs) {
    expect(opml).toContain(`xmlUrl="${feed_url.replaceAll("&", "&amp;")}"`);
  }
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the drawer holds the theme switch and the export, and no shortcuts button", async ({
    page,
  }) => {
    await page.goto("/app/");
    await page.getByRole("button", { name: "Open feeds" }).click();
    const drawer = page.getByRole("dialog");
    await expect(drawer.getByRole("group", { name: "Colour theme" })).toBeVisible();
    await expect(drawer.getByRole("button", { name: "Export feeds (OPML)" })).toBeVisible();
    await expect(drawer.getByRole("button", { name: "Keyboard shortcuts" })).toBeHidden();
  });
});
