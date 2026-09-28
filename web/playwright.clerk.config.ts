import { defineConfig, devices } from "@playwright/test";

// The Clerk-mode suite. scripts/e2e-clerk.sh brings the stack up in AUTH_MODE=clerk,
// creates and seeds this run's Clerk test user, and deletes it afterwards; Playwright
// drives the browser. Kept apart from playwright.config.ts because the default suite
// runs AUTH_MODE=none and knows nothing about Clerk.
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost";

export default defineConfig({
  testDir: "./e2e-clerk",
  globalSetup: "./e2e-clerk/global-setup.ts",
  // One user, shared state, and a real Clerk instance with rate limits: serial.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  // Short on purpose: a stuck step should fail in seconds, not hold the run for
  // minutes. The token-refresh test raises its own limit (it waits out the token).
  timeout: 45_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL,
    // No traces in CI: the repo is public, failed runs upload test-results/ as an
    // artifact, and a trace records request headers, which include the Clerk
    // testing token (bot-protection bypass for about an hour) and session tokens.
    // Screenshots and the error context show the page without them.
    trace: process.env.CI ? "off" : "on-first-retry",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 20_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
