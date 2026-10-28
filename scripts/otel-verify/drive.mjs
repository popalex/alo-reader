// Drives the SPA so the browser emits its ui.* spans, and records each OTLP POST.
//   node drive.mjs subscribe   ui.subscribe (discover, then POST /subscriptions)
//   node drive.mjs read        ui.open_article, ui.search
// Prints one JSON object: the steps and how each went, OTLP response statuses, and
// console errors. A failed step is recorded, not thrown, so the checks still run.
import { createRequire } from "node:module";

// Playwright comes from web/, the only place it is installed.
const require = createRequire(new URL("../../web/package.json", import.meta.url));
const { chromium } = require("@playwright/test");

const BASE = process.env.BASE_URL ?? "http://localhost";
const phase = process.argv[2];
const out = { phase, otlp: [], consoleErrors: [], steps: [] };
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("console", (m) => m.type() === "error" && out.consoleErrors.push(m.text()));
page.on("response", (r) => {
  if (r.url().includes("/otlp/")) out.otlp.push(r.status());
});

const step = async (name, fn) => {
  try {
    await fn();
    out.steps.push([name, "ok"]);
  } catch (e) {
    out.steps.push([name, String(e).split("\n")[0]]);
  }
};

await step("load", () => page.goto(`${BASE}/app/`, { waitUntil: "networkidle" }));
if (phase === "subscribe") {
  await step("subscribe", async () => {
    await page.getByRole("button", { name: "Subscribe", exact: true }).click();
    await page.getByLabel(/feed or site url/i).fill("http://feedfixture/rss.xml");
    await page.getByRole("button", { name: /find/i }).click();
    await page.getByRole("button", { name: /^add/i }).first().click({ timeout: 15000 });
    await page.getByRole("heading", { name: "Subscribe to a feed" }).waitFor({ state: "detached" });
  });
} else {
  await step("open-article", async () => {
    await page.waitForSelector("[data-index]", { timeout: 15000 });
    await page.locator("[data-index='0']").click();
    await page.locator("article").getByRole("heading", { level: 1 }).waitFor();
  });
  await step("search", async () => {
    await page.getByRole("searchbox", { name: "Search articles" }).fill("smoke");
    await page.waitForTimeout(2500);
  });
}
// The web BatchSpanProcessor exports on a timer; stay past it, then leave the page so
// anything still queued is flushed on unload.
await page.waitForTimeout(8000);
await page.goto("about:blank");
await page.waitForTimeout(1500);
await browser.close();
console.log(JSON.stringify(out));
