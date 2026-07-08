import { expect, test } from "@playwright/test";

// WP-12 acceptance: a full session driven ONLY by the keyboard. The initial
// page load is the one allowed non-keyboard action (there is no subscribe flow
// yet — the seed provides feeds); everything after is page.keyboard.*, no
// mouse. Runs serially against the shared seeded stack, so its one destructive
// step (mark-all) is scoped to the Starred stream, not All items.

test.describe("keyboard-only session", () => {
  test("navigate, open, act, switch streams and mark-all with no mouse", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("[data-index]");

    // j puts the keyboard cursor on the first row: a visible ring + real focus.
    await page.keyboard.press("j");
    await expect(page.locator("[data-cursor]")).toHaveAttribute("data-index", "0");
    await expect
      .poll(() => page.evaluate(() => document.activeElement?.getAttribute("role")))
      .toBe("listitem");

    // j/k move the cursor ONLY — they must not open the reader or mark anything
    // (opening/marking is o/Enter's job). The reader stays on its empty state.
    await page.keyboard.press("j"); // -> row 1
    await expect(page.locator("[data-cursor]")).toHaveAttribute("data-index", "1");
    await expect(page.getByText("Select an article")).toBeVisible();
    await expect(page.locator("article h1")).toHaveCount(0);
    await page.keyboard.press("k"); // -> back to row 0, still not opened
    await expect(page.locator("[data-cursor]")).toHaveAttribute("data-index", "0");
    await expect(page.getByText("Select an article")).toBeVisible();

    // Land the cursor on a real article (row 0 is the XSS probe) before acting.
    await page.keyboard.press("j");

    // s stars the cursor row without opening it.
    await page.keyboard.press("s");

    // o opens the cursor row in the reader (and marks it read).
    await page.keyboard.press("o");
    await expect(page.locator("article h1")).toBeVisible();

    // m toggles read state; the reader action label flips to reflect it.
    await page.keyboard.press("m");
    await expect(page.getByRole("button", { name: /Mark unread/ })).toHaveCount(0);

    // v opens the original in a new tab.
    const [popup] = await Promise.all([page.waitForEvent("popup"), page.keyboard.press("v")]);
    expect(popup.url()).toContain("seed.dev");
    await popup.close();

    // ? opens the help overlay (generated from the binding table); Esc closes it.
    await page.keyboard.press("?");
    const help = page.getByRole("dialog", { name: "Keyboard shortcuts" });
    await expect(help).toBeVisible();
    await expect(help.getByText("Go to All items")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(help).toBeHidden();

    // o again closes the reader and returns focus to the cursor row (predictable
    // focus after the pane closes — no focus lost to <body>).
    await page.keyboard.press("o");
    await expect(page.getByText("Select an article")).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.activeElement?.getAttribute("role")))
      .toBe("listitem");

    // g s switches to the Starred stream.
    await page.keyboard.press("g");
    await page.keyboard.press("s");
    await expect(page.getByRole("heading", { name: "Starred", level: 1 })).toBeVisible();
    await page.waitForSelector("[data-index]");

    // A on Starred asks to confirm; Enter confirms — fully keyboard-driven.
    await page.keyboard.press("A");
    const confirm = page.getByRole("dialog", { name: "Mark all as read?" });
    await expect(confirm).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(confirm).toBeHidden();

    // g a switches back to All items.
    await page.keyboard.press("g");
    await page.keyboard.press("a");
    await expect(page.getByRole("heading", { name: "All items", level: 1 })).toBeVisible();

    // / focuses the (WP-13) search input.
    await page.keyboard.press("/");
    await expect(page.getByRole("searchbox", { name: "Search articles" })).toBeFocused();
  });
});
