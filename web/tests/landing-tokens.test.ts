// The landing page copies its colours from tokens.css rather than linking it: the
// built stylesheet is content-hashed, so a <link> would couple a static page to a
// build artefact's filename. Copies rot, so this test is the thing that notices.
//
// Same idea as tests/test_env_template.py on the API side: the duplicate is allowed
// to exist, but it is not allowed to disagree.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const repoRoot = resolve(__dirname, "../..");
const tokensCss = readFileSync(resolve(repoRoot, "web/src/styles/tokens.css"), "utf8");
const landingHtml = readFileSync(resolve(repoRoot, "deploy/landing/landing.html"), "utf8");

/** The landing page renames two tokens; everything else matches by name. */
const ALIASES: Record<string, string> = {
  "--line": "--border",
  "--line-2": "--border-2",
};

/** Colour declarations inside the first block matching `selector`. */
function blockVars(css: string, selector: string): Map<string, string> {
  const start = css.indexOf(selector);
  if (start < 0) throw new Error(`no ${selector} block`);
  // Match braces rather than looking for a "\n}" — the landing page's CSS is
  // indented inside <style>, so a naive search runs past the block's end and
  // swallows every later block, which silently compares the wrong values.
  const open = css.indexOf("{", start);
  let depth = 0;
  let close = open;
  for (let i = open; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}") {
      depth--;
      if (depth === 0) {
        close = i;
        break;
      }
    }
  }
  const body = css.slice(open, close);
  const vars = new Map<string, string>();
  for (const [, name, value] of body.matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)) {
    vars.set(name, value.trim());
  }
  return vars;
}

function landingVars(selector: string): Map<string, string> {
  const style = landingHtml.slice(landingHtml.indexOf("<style>"), landingHtml.indexOf("</style>"));
  return blockVars(style, selector);
}

describe("landing page tokens", () => {
  it("light values match tokens.css", () => {
    const app = blockVars(tokensCss, ":root {");
    const landing = landingVars(":root {");
    const drift: string[] = [];
    for (const [name, value] of landing) {
      const appName = ALIASES[name] ?? name;
      const appValue = app.get(appName);
      if (appValue === undefined) continue; // page-only token (e.g. --font-sans copy)
      if (appValue !== value) drift.push(`${name}: landing ${value} vs tokens.css ${appValue}`);
    }
    expect(drift).toEqual([]);
  });

  it("dark values match tokens.css", () => {
    const app = blockVars(tokensCss, ':root[data-theme="dark"] {');
    const landing = landingVars("@media (prefers-color-scheme: dark)");
    const drift: string[] = [];
    for (const [name, value] of landing) {
      const appName = ALIASES[name] ?? name;
      const appValue = app.get(appName);
      if (appValue === undefined) continue;
      if (appValue !== value) drift.push(`${name}: landing ${value} vs tokens.css ${appValue}`);
    }
    expect(drift).toEqual([]);
  });
});
