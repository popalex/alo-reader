// A var() that nothing declares renders as nothing: no border, or a fallback colour
// meant for the other theme. Review doesn't catch it and neither does the build. The
// welcome screen shipped with --line/--line-2 (the landing page's names), so its
// cards had no borders, and the crashed-pane button asked for --accent-fg and got
// white on the dark accent.

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "../src");

function cssFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? cssFiles(join(dir, e.name)) : e.name.endsWith(".css") ? [join(dir, e.name)] : [],
  );
}

describe("CSS custom properties", () => {
  it("every var() in web/src names a property some stylesheet declares", () => {
    const sources = cssFiles(SRC).map((f) => [f, readFileSync(f, "utf8")] as const);
    const declared = new Set(sources.flatMap(([, css]) => [...css.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1])));
    const missing = sources.flatMap(([file, css]) =>
      [...css.matchAll(/var\(\s*(--[\w-]+)/g)]
        .map((m) => m[1])
        .filter((name) => !declared.has(name))
        .map((name) => `${file.slice(SRC.length + 1)}: ${name}`),
    );
    expect(missing).toEqual([]);
  });
});
