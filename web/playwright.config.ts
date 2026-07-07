import { defineConfig, devices } from "@playwright/test";

// The stack (API + worker + Postgres + Caddy-served SPA + fixture feed) is
// brought up and seeded by scripts/e2e.sh; Playwright just drives the browser
// against it. E2E_BASE_URL lets that script (or a dev) point elsewhere.
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  timeout: 30_000,
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
