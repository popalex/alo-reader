// initBrowserTelemetry sets the tracer provider, propagator and context manager
// itself, since SDK 3.0 has no provider.register(). The other trace tests build their
// own provider with a StackContextManager, which works whether or not it was enabled,
// so they cannot tell if this wiring is right. This one runs the real function, zone
// manager and all, and checks what a fetch actually sends.

import { context, propagation, trace } from "@opentelemetry/api";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { initBrowserTelemetry } from "../src/app/telemetry";

const realFetch = globalThis.fetch;
const apiCalls: Headers[] = [];

beforeAll(async () => {
  globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).includes("/api/")) apiCalls.push(new Headers(init?.headers));
    return Promise.resolve(new Response("{}", { status: 200 }));
  }) as typeof fetch;
  initBrowserTelemetry({ serviceName: "alo-web-test", exportUrl: "/otlp/v1/traces" });
  // The SDK arrives through dynamic imports; the propagator is set once it has.
  await vi.waitFor(() => expect(propagation.fields()).toContain("traceparent"), {
    timeout: 5000,
  });
});

afterAll(() => {
  trace.disable();
  propagation.disable();
  context.disable();
  globalThis.fetch = realFetch;
});

describe("initBrowserTelemetry", () => {
  it("sends the active span's trace on an /api call", async () => {
    const traceId = await trace.getTracer("test").startActiveSpan("ui.test", async (span) => {
      await fetch("/api/v1/counts");
      span.end();
      return span.spanContext().traceId;
    });

    expect(apiCalls).toHaveLength(1);
    expect(apiCalls[0].get("traceparent")).toMatch(new RegExp(`^00-${traceId}-`));
  });

  it("keeps a context entered with context.with()", () => {
    // What api/client.ts does to parent a write to its UI action. A context manager
    // that was never enabled answers the root context here.
    const span = trace.getTracer("test").startSpan("ui.test");
    const seen = context.with(trace.setSpan(context.active(), span), () =>
      trace.getSpan(context.active()),
    );
    span.end();
    expect(seen).toBe(span);
  });
});
