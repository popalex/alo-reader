// UI-action spans. When browser telemetry is enabled (app/telemetry.ts) these nest
// under the active trace and — for the awaited variant — parent the fetch they trigger,
// so Tempo shows one continuous ui.subscribe → POST /api/... → backend trace. When
// telemetry is off the global tracer is a no-op, so both helpers are free.

import { SpanStatusCode, trace } from "@opentelemetry/api";

type Attrs = Record<string, string | number | boolean>;

function tracer() {
  return trace.getTracer("alo-web");
}

/** Wrap an async action (one that awaits a fetch) in a `ui.<name>` span. */
export async function traceUiAction<T>(name: string, attributes: Attrs, fn: () => Promise<T>): Promise<T> {
  return tracer().startActiveSpan(name, async (span) => {
    for (const [key, value] of Object.entries(attributes)) span.setAttribute(key, value);
    try {
      return await fn();
    } catch (error) {
      span.recordException(error as Error);
      span.setStatus({ code: SpanStatusCode.ERROR });
      throw error;
    } finally {
      span.end();
    }
  });
}

/** Record a point-in-time UI interaction (for React-Query-driven actions whose fetch
 *  isn't awaited in the handler) as a short span, so it still shows on the trace. */
export function markUiEvent(name: string, attributes: Attrs = {}): void {
  const span = tracer().startSpan(name);
  for (const [key, value] of Object.entries(attributes)) span.setAttribute(key, value);
  span.end();
}
