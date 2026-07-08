import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// WP-12 accessibility gate: axe-core finds no violations on the main surfaces
// (list, reader, help overlay). Non-destructive — opens a single entry — so
// order among the serial specs doesn't matter.
//
// color-contrast is excluded on purpose: the palette is fixed by the design
// tokens (web/src/styles/tokens.css, WP-09) whose muted secondary text is a
// deliberate product choice, and contrast is tracked by the Lighthouse budget
// (`make lighthouse`). This gate guards the structural/ARIA a11y that WP-12
// owns: roles, names, landmarks, focus order.
const axe = (page: import("@playwright/test").Page) =>
  new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).disableRules(["color-contrast"]);

test.describe("accessibility", () => {
  test("no violations on list, reader and help overlay", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("[data-index]");
    expect((await axe(page).analyze()).violations).toEqual([]);

    // Reader pane.
    await page.keyboard.press("j");
    await page.keyboard.press("o");
    await expect(page.locator("article h1")).toBeVisible();
    expect((await axe(page).analyze()).violations).toEqual([]);

    // Help overlay (modal dialog).
    await page.keyboard.press("?");
    await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
    expect((await axe(page).analyze()).violations).toEqual([]);
  });
});
