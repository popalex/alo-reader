// UI-action spans. When browser telemetry is enabled (app/telemetry.ts) these nest
// under the active trace and — for the awaited variant — parent the fetch they trigger,
// so Tempo shows one continuous ui.subscribe → POST /api/... → backend trace. When
// telemetry is off the global tracer is a no-op, so both helpers are free.

import { type Context, context, SpanStatusCode, trace } from "@opentelemetry/api";

type Attrs = Record<string, string | number | boolean>;

function tracer() {
  return trace.getTracer("alo-web");
}

// The context of the UI action in progress, for api/client.ts. startActiveSpan alone
// is not enough: ZoneContextManager cannot follow native async/await (the build
// targets ES2022), and TanStack Query awaits internally before it calls the
// mutationFn, so by the time fetch runs the active context is empty and the POST
// became its own trace instead of a child of ui.subscribe.
// A list, not a single slot restored on exit: actions can finish out of order, and
// restoring "the previous one" would then bring back a span that had already ended
// and attach every later write to it.
const pendingUiActions: Context[] = [];

/** The context of the latest `ui.*` action still awaiting its fetch, if any. */
export function pendingUiActionContext(): Context | undefined {
  return pendingUiActions.at(-1);
}

/** Wrap an async action (one that awaits a fetch) in a `ui.<name>` span. */
export async function traceUiAction<T>(name: string, attributes: Attrs, fn: () => Promise<T>): Promise<T> {
  return tracer().startActiveSpan(name, async (span) => {
    for (const [key, value] of Object.entries(attributes)) span.setAttribute(key, value);
    const ctx = trace.setSpan(context.active(), span);
    pendingUiActions.push(ctx);
    try {
      return await fn();
    } catch (error) {
      span.recordException(error as Error);
      span.setStatus({ code: SpanStatusCode.ERROR });
      throw error;
    } finally {
      pendingUiActions.splice(pendingUiActions.indexOf(ctx), 1);
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
