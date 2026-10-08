import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { extname, join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

// What a returning user sees after a deploy. The service worker precaches the app, so
// the first visit after a deploy is still the old build, served from the cache. That
// visit's update check installs the new worker, which takes over (skipWaiting,
// clientsClaim) and drops the old cache, so the next visit is the new build. The trap
// this guards against is a worker that never updates: then users are stuck on an old
// build until they clear site data, which is what `make dev` did to a stale production
// worker on 2026-10-08, because the dev server answers /app/sw.js with index.html.
//
// Two real builds of the same source, differing only by one marker statement that
// e2e/deploy-build.config.ts appends to src/main.tsx, so B has new hashes and a new
// precache manifest.
// A small server stands in for Caddy's /app/ rules (deploy/Caddyfile) and switches
// from A to B mid-test, the way a deploy swaps the files. It doesn't use the e2e
// stack: the API isn't needed to see which build a page loaded.

const WEB_ROOT = new URL("..", import.meta.url).pathname;

const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".webmanifest": "application/manifest+json",
  ".json": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
};

let workDir = "";
let builds: Record<"a" | "b", string> = { a: "", b: "" };
let serving: "a" | "b" = "a";
let server: Server;
let origin = "";

function build(name: "a" | "b"): string {
  const outDir = join(workDir, name);
  const config = "e2e/deploy-build.config.ts";
  const args = ["exec", "vite", "build", "-c", config, "--outDir", outDir, "--emptyOutDir"];
  execFileSync("pnpm", args, {
    cwd: WEB_ROOT,
    env: { ...process.env, ALO_E2E_BUILD: name },
    stdio: ["ignore", "ignore", "inherit"],
  });
  return outDir;
}

function isFile(path: string): boolean {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
}

/** Caddy's /app/ handling, reduced to what a deploy changes: hashed assets are
 *  immutable and a missing one is a real 404; the shell and sw.js are no-cache;
 *  any other path gets index.html. */
function serve(path: string): { status: number; file?: string; cache?: string } {
  if (!path.startsWith("/app/")) return { status: 404 };
  const root = builds[serving];
  const file = join(root, path.slice("/app/".length));
  if (path.startsWith("/app/assets/")) {
    if (!isFile(file)) return { status: 404 };
    return { status: 200, file, cache: "public, max-age=31536000, immutable" };
  }
  if (path !== "/app/" && isFile(file)) {
    const shell = ["/app/index.html", "/app/manifest.webmanifest", "/app/sw.js"].includes(path);
    return { status: 200, file, cache: shell ? "no-cache" : "public, max-age=3600" };
  }
  return { status: 200, file: join(root, "index.html"), cache: "no-cache" };
}

test.beforeAll(async () => {
  test.setTimeout(240_000);
  workDir = mkdtempSync(join(tmpdir(), "alo-deploy-"));
  builds = { a: build("a"), b: build("b") };
  server = createServer((req, res) => {
    const { status, file, cache } = serve(new URL(req.url ?? "/", "http://x").pathname);
    if (!file) {
      res.writeHead(status, { "Content-Type": "text/plain" }).end("not found");
      return;
    }
    const type = TYPES[extname(file)] ?? "application/octet-stream";
    const headers: Record<string, string> = { "Content-Type": type };
    if (cache) headers["Cache-Control"] = cache;
    res.writeHead(status, headers).end(readFileSync(file));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  // localhost, not 127.0.0.1, in the page's origin: both are secure contexts, but this
  // keeps the URL shaped like the real one. Its own port, so it can't share a service
  // worker with the e2e stack on :80.
  origin = `http://localhost:${(server.address() as AddressInfo).port}`;
});

test.afterAll(async () => {
  await new Promise<void>((resolve) => server?.close(() => resolve()));
  if (workDir) rmSync(workDir, { recursive: true, force: true });
});

/** The entry script the page loaded: it names the build (assets/app-<hash>.js). */
function entryScript(page: Page): Promise<string | null> {
  return page.locator('script[type="module"][src*="/assets/app-"]').getAttribute("src");
}

function entryIn(name: "a" | "b"): string {
  const html = readFileSync(join(builds[name], "index.html"), "utf8");
  const src = /src="([^"]*\/assets\/app-[^"]+\.js)"/.exec(html)?.[1];
  if (!src) throw new Error(`no entry script in build ${name}`);
  return src;
}

test("after a deploy, the next visit is the old build from cache and the one after is the new build", async ({
  page,
}) => {
  const [a, b] = [entryIn("a"), entryIn("b")];
  expect(a).not.toBe(b);

  // A returning user: build A loaded, and its worker installed and in control.
  serving = "a";
  await page.goto(`${origin}/app/`);
  expect(await entryScript(page)).toBe(a);
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, { timeout: 20_000 });

  // Deploy.
  serving = "b";

  // The first visit after it is still A, answered by the worker from its cache...
  await page.reload();
  expect(await entryScript(page)).toBe(a);

  // ...and that visit's update check installs B's worker, which replaces A's cached
  // shell with B's. Polled from the page: the precache is what the next visit gets.
  await expect
    .poll(
      () =>
        page.evaluate(async () => {
          const shell = await caches.match("/app/index.html", { ignoreSearch: true });
          return shell ? await shell.text() : "";
        }),
      { timeout: 30_000, message: "the new service worker never took over" },
    )
    .toContain(b);

  // The visit after that is B.
  await page.reload();
  expect(await entryScript(page)).toBe(b);
});
