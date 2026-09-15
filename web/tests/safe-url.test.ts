// The render-site half of the javascript:-URL fix. The parser stops new ones being
// stored (api #69), but rows ingested before that are still in the database, and
// React only refuses such an href in development builds.

import { describe, expect, it } from "vitest";

import { safeExternalUrl } from "../src/lib/url";

describe("safeExternalUrl", () => {
  it("keeps http and https", () => {
    expect(safeExternalUrl("https://example.com/post")).toBe("https://example.com/post");
    expect(safeExternalUrl("http://example.com/post")).toBe("http://example.com/post");
  });

  it("keeps a relative URL, which inherits the page's scheme", () => {
    expect(safeExternalUrl("/relative/path")).toBe("/relative/path");
  });

  it.each([
    "javascript:alert(document.cookie)",
    "JavaScript:alert(1)",
    "  javascript:alert(1)  ",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
  ])("refuses %s", (url) => {
    expect(safeExternalUrl(url)).toBeUndefined();
  });

  it("refuses nothing at all", () => {
    expect(safeExternalUrl(null)).toBeUndefined();
    expect(safeExternalUrl(undefined)).toBeUndefined();
    expect(safeExternalUrl("")).toBeUndefined();
  });
});
