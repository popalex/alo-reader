// A ui.* action and the write it triggers belong in one trace. They did not:
// ZoneContextManager cannot follow native async/await, and TanStack Query awaits
// before it calls the mutationFn, so the POST started with an empty context and
// became a separate trace. These tests lose the context the same way (an await on
// a timer) and check the fetch span still lands under the ui span.

import { context, trace } from "@opentelemetry/api";
import { registerInstrumentations } from "@opentelemetry/instrumentation";
import { FetchInstrumentation } from "@opentelemetry/instrumentation-fetch";
import {
  InMemorySpanExporter,
  SimpleSpanProcessor,
  StackContextManager,
  WebTracerProvider,
} from "@opentelemetry/sdk-trace-web";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { createSubscription, getCounts } from "../src/api/endpoints";
import { traceUiAction } from "../src/app/traceUiAction";

const exporter = new InMemorySpanExporter();
const realFetch = globalThis.fetch;
let teardown: () => void;

beforeAll(() => {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve(new Response(JSON.stringify({ id: 1 }), { status: 201 })),
  ) as typeof fetch;
  const provider = new WebTracerProvider({ spanProcessors: [new SimpleSpanProcessor(exporter)] });
  provider.register({ contextManager: new StackContextManager() });
  teardown = registerInstrumentations({
    tracerProvider: provider,
    instrumentations: [new FetchInstrumentation()],
  });
});

afterAll(() => {
  teardown();
  trace.disable();
  context.disable();
  globalThis.fetch = realFetch;
});

beforeEach(() => exporter.reset());

const lostContext = () => new Promise((resolve) => setTimeout(resolve, 0));

async function finished(names: string[]) {
  await vi.waitFor(
    () => expect(exporter.getFinishedSpans().map((s) => s.name)).toEqual(
      expect.arrayContaining(names),
    ),
    { timeout: 2000 },
  );
  return exporter.getFinishedSpans();
}

describe("traceUiAction", () => {
  it("parents the write it triggers even after the async context is lost", async () => {
    await traceUiAction("ui.subscribe", {}, async () => {
      await lostContext();
      expect(trace.getSpan(context.active())).toBeUndefined(); // the loss is real
      return createSubscription(null, { feed_url: "https://example.com/feed" });
    });

    const spans = await finished(["ui.subscribe", "POST"]);
    const ui = spans.find((s) => s.name === "ui.subscribe")!;
    const post = spans.find((s) => s.name === "POST")!;
    expect(post.spanContext().traceId).toBe(ui.spanContext().traceId);
    expect(post.parentSpanContext?.spanId).toBe(ui.spanContext().spanId);
  });

  it("does not adopt a background GET that runs during the action", async () => {
    await traceUiAction("ui.subscribe", {}, async () => {
      await lostContext();
      await getCounts(null).catch(() => undefined);
    });

    const spans = await finished(["ui.subscribe", "GET"]);
    const ui = spans.find((s) => s.name === "ui.subscribe")!;
    const get = spans.find((s) => s.name === "GET")!;
    expect(get.spanContext().traceId).not.toBe(ui.spanContext().traceId);
  });

  it("forgets an action once it ends, even when actions finish out of order", async () => {
    // a starts, b starts, a ends, b ends. Restoring "whatever was pending when I
    // started" on exit would have b bring back a, which by then has already ended.
    let finishA!: () => void;
    let finishB!: () => void;
    const a = traceUiAction("ui.a", {}, () => new Promise<void>((r) => (finishA = r)));
    const b = traceUiAction("ui.b", {}, () => new Promise<void>((r) => (finishB = r)));
    finishA();
    await a;
    finishB();
    await b;

    await createSubscription(null, { feed_url: "https://example.com/feed" });
    const spans = await finished(["ui.a", "ui.b", "POST"]);
    expect(spans.find((s) => s.name === "POST")!.parentSpanContext).toBeUndefined();
  });

  it("leaves writes outside any action alone", async () => {
    await createSubscription(null, { feed_url: "https://example.com/feed" });
    const [post] = await finished(["POST"]);
    expect(post.parentSpanContext).toBeUndefined();
  });
});
