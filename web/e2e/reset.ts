import { execSync } from "node:child_process";

// Put the seeded user's data back to exactly what scripts/seed_dev.py creates.
//
// The specs run serially against one backend, and several of them change it: mark
// entries read, star them, rename and delete feeds and categories, import OPML. They
// used to share whatever the previous file left behind, so a reordered file, a new
// destructive spec or a retry could fail a PR that touched nothing nearby: running the
// mutating specs twice in a row failed 7 tests on the second pass. Every spec file
// now calls this in beforeAll. A retried test runs in a fresh worker, which runs
// beforeAll again, so it starts clean too.
//
// scripts/e2e.sh provides the command (a reseed inside the api container, ~3 s).
// Without it, for example Playwright pointed at some other stack, nothing is reset
// and the specs run against whatever is there.
export function resetSeedData(): void {
  const command = process.env.E2E_RESET_CMD;
  if (!command) {
    console.warn("E2E_RESET_CMD is not set: not resetting the seeded data (run via scripts/e2e.sh)");
    return;
  }
  execSync(command, { stdio: ["ignore", "ignore", "inherit"], cwd: new URL("../..", import.meta.url).pathname });
}

/** Leave the seeded user with no folders and no feeds: a brand-new account. Done in
 *  the database (scripts/e2e.sh provides the command) rather than by deleting feeds
 *  through the API, where 20 deletes in a row ran into the per-user rate limit and
 *  left the test itself without requests to spend. */
export function emptyAccount(): void {
  const command = process.env.E2E_EMPTY_CMD;
  if (!command) {
    throw new Error("E2E_EMPTY_CMD is not set: the welcome-screen specs need scripts/e2e.sh");
  }
  execSync(command, { stdio: ["ignore", "ignore", "inherit"], cwd: new URL("../..", import.meta.url).pathname });
}
