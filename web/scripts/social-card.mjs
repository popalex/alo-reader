// The social card (og:image / twitter:image) is the landing page itself, rendered at
// card size. Generated rather than drawn, so it cannot drift from the page: rerun it
// after changing deploy/landing/landing.html (`make social-card`) and commit the PNG.
//
// A card is seen at thumbnail size, so the page's small print (nav links, the
// paragraph, the button) is hidden and the headline and the app mock under it get
// the space. Everything else is the page as a visitor sees it, fonts included.
import { existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const landing = fileURLToPath(new URL("../../deploy/landing/", import.meta.url));
const out = join(landing, "og-card.png");
const TYPES = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".woff2": "font/woff2" };

const CARD_CSS = `
  .navlinks, .eyebrow, .hero .sub, .hero .btn, .hero .reassure { display: none !important; }
  .hero { padding-top: 34px !important; padding-bottom: 30px !important; }
  h1 { font-size: 64px !important; max-width: 18ch !important; margin-bottom: 0 !important; }
  .shotwrap ~ * , footer { display: none !important; }
`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, colorScheme: "light" });
await page.route("http://card.local/**", (route) => {
  const path = new URL(route.request().url()).pathname;
  const file = join(landing, path === "/" ? "landing.html" : path.slice(1));
  if (!existsSync(file)) return route.fulfill({ status: 404, body: "" });
  const ext = file.slice(file.lastIndexOf("."));
  return route.fulfill({ status: 200, contentType: TYPES[ext] ?? "application/octet-stream", body: readFileSync(file) });
});
await page.goto("http://card.local/", { waitUntil: "networkidle" });
await page.addStyleTag({ content: CARD_CSS });
await page.evaluate(() => document.fonts.ready);
const family = await page.evaluate(() =>
  [...document.fonts].some((f) => f.family.includes("Inter") && f.status === "loaded"),
);
if (!family) throw new Error("Inter did not load; the card would render in a fallback font");
await page.screenshot({ path: out });
await browser.close();
console.log(`wrote ${out} (${Math.round(statSync(out).size / 1024)} kB)`);
