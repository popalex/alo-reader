// The browser exports its own spans straight to /otlp, so scrubbing the API's
// spans and logs is not enough on its own: FetchInstrumentation puts the full
// request URL on a client span, query string included.

import { describe, expect, it } from "vitest";

import { scrubQueryString } from "../src/app/telemetry";

function fakeSpan(attributes: Record<string, unknown>) {
  return {
    attributes,
    setAttribute(key: string, value: string) {
      this.attributes[key] = value;
    },
  };
}

describe("scrubQueryString", () => {
  it("strips the query from every URL attribute", () => {
    const span = fakeSpan({
      "http.url": "https://alo.example/api/v1/streams/all/entries?q=private+terms&limit=50",
      "url.full": "https://alo.example/api/v1/streams/all/entries?q=private+terms",
      "http.target": "/api/v1/streams/all/entries?q=private+terms",
    });
    scrubQueryString(span);
    expect(span.attributes["http.url"]).toBe(
      "https://alo.example/api/v1/streams/all/entries?[scrubbed]",
    );
    expect(span.attributes["url.full"]).toBe(
      "https://alo.example/api/v1/streams/all/entries?[scrubbed]",
    );
    expect(span.attributes["http.target"]).toBe("/api/v1/streams/all/entries?[scrubbed]");
    expect(JSON.stringify(span.attributes)).not.toContain("private");
  });

  it("leaves URLs without a query alone", () => {
    const span = fakeSpan({ "http.url": "https://alo.example/api/v1/entries" });
    scrubQueryString(span);
    expect(span.attributes["http.url"]).toBe("https://alo.example/api/v1/entries");
  });

  it("does nothing for a span-shaped object it cannot write to", () => {
    expect(() => scrubQueryString({ attributes: { "http.url": "/x?q=1" } })).not.toThrow();
    expect(() => scrubQueryString(undefined)).not.toThrow();
  });
});
