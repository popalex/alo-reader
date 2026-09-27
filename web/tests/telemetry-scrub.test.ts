// The browser exports its own spans straight to /otlp, so scrubbing the API's
// spans and logs is not enough on its own: FetchInstrumentation puts the full
// request URL on a client span, query string included.

import { registerInstrumentations } from "@opentelemetry/instrumentation";
import { FetchInstrumentation } from "@opentelemetry/instrumentation-fetch";
import {
  InMemorySpanExporter,
  SimpleSpanProcessor,
  WebTracerProvider,
} from "@opentelemetry/sdk-trace-web";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryScrubProcessor, scrubQueryString } from "../src/app/telemetry";

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

describe("queryScrubProcessor with the real fetch instrumentation", () => {
  const realFetch = globalThis.fetch;
  let teardown: (() => void) | undefined;

  afterEach(() => {
    teardown?.();
    globalThis.fetch = realFetch;
  });

  // No applyCustomAttributesOnSpan hook here on purpose: the processor alone has to
  // be enough, because the instrumentation skips that hook on some exit paths.
  async function exportedUrlsFor(fetchImpl: typeof fetch): Promise<string[]> {
    globalThis.fetch = fetchImpl;
    const exporter = new InMemorySpanExporter();
    const provider = new WebTracerProvider({
      spanProcessors: [queryScrubProcessor, new SimpleSpanProcessor(exporter)],
    });
    teardown = registerInstrumentations({
      tracerProvider: provider,
      instrumentations: [new FetchInstrumentation()],
    });

    await fetch("/api/v1/streams/all/entries?q=private+terms").catch(() => undefined);
    // The instrumentation ends the span on a timer, to collect resource timings.
    await vi.waitFor(() => expect(exporter.getFinishedSpans()).toHaveLength(1), {
      timeout: 2000,
    });
    return exporter
      .getFinishedSpans()
      .flatMap((span) => Object.values(span.attributes))
      .map(String);
  }

  it("scrubs a fetch that fails", async () => {
    const urls = await exportedUrlsFor(() => Promise.reject(new TypeError("offline")));
    expect(urls.join(" ")).not.toContain("private");
    expect(urls.some((u) => u.endsWith("/api/v1/streams/all/entries?[scrubbed]"))).toBe(true);
  });

  it("scrubs a response the instrumentation cannot clone", async () => {
    // clone() throwing sends FetchInstrumentation down a path that ends the span
    // without calling applyCustomAttributesOnSpan.
    const response = new Response("{}");
    response.clone = () => {
      throw new Error("no clone");
    };
    const urls = await exportedUrlsFor(() => Promise.resolve(response));
    expect(urls.join(" ")).not.toContain("private");
  });
});
