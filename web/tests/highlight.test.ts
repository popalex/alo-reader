import { describe, expect, it } from "vitest";

import { highlightSnippet } from "../src/lib/highlight";

describe("highlightSnippet", () => {
  it("keeps the API's <b> match markers", () => {
    expect(highlightSnippet("the <b>quick</b> fox")).toBe("the <b>quick</b> fox");
  });

  it("escapes markup in the surrounding text", () => {
    expect(highlightSnippet('<script>alert("x")</script>')).toBe(
      '&lt;script&gt;alert("x")&lt;/script&gt;',
    );
    expect(highlightSnippet("Tom & Jerry")).toBe("Tom &amp; Jerry");
  });

  it("does not resurrect literal entity text into a tag", () => {
    // Content that literally contains the characters "&lt;b&gt;" must stay inert.
    const out = highlightSnippet("&lt;b&gt;evil");
    expect(out).toBe("&amp;lt;b&amp;gt;evil");
    expect(out).not.toContain("<b>");
  });

  it("highlights within otherwise-escaped content", () => {
    expect(highlightSnippet("a <b>x</b> & <y>")).toBe("a <b>x</b> &amp; &lt;y&gt;");
  });
});
