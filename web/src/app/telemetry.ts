// Browser OpenTelemetry, initialised only when /config reports otel_enabled. The SDK
// is heavy (~tens of kB), so it's brought in via dynamic import() — a separate lazy
// chunk that never touches the initial bundle (nor the size-limit budget) when
// telemetry is off. Document-load + fetch instrumentation propagate `traceparent` into
// /api requests, so a browser trace continues into the backend as one waterfall.

let initialized = false;

export interface BrowserTelemetryOptions {
  serviceName: string;
  exportUrl: string;
}

/** Span attribute names that can carry a URL, across semconv versions. */
const URL_ATTRS = ["http.url", "url.full", "http.target"] as const;

/**
 * Replace the query string on a span's URL attributes with `[scrubbed]`.
 *
 * The backend does this in two other places — app/telemetry.py for its server span,
 * app/sentry.py for error events — because a search query is the most personal thing
 * these URLs carry. The browser exports straight to /otlp, so it is the third door.
 */
export function scrubQueryString(span: unknown): void {
  const s = span as {
    attributes?: Record<string, unknown>;
    setAttribute?: (k: string, v: string) => void;
  };
  if (!s || typeof s.setAttribute !== "function") return;
  for (const name of URL_ATTRS) {
    const value = s.attributes?.[name];
    if (typeof value === "string" && value.includes("?")) {
      s.setAttribute(name, `${value.split("?")[0]}?[scrubbed]`);
    }
  }
}

export function initBrowserTelemetry({ serviceName, exportUrl }: BrowserTelemetryOptions): void {
  if (initialized) return;
  initialized = true;

  void Promise.all([
    import("@opentelemetry/context-zone"),
    import("@opentelemetry/exporter-trace-otlp-http"),
    import("@opentelemetry/instrumentation"),
    import("@opentelemetry/instrumentation-fetch"),
    import("@opentelemetry/resources"),
    import("@opentelemetry/sdk-trace-web"),
    import("@opentelemetry/core"),
  ])
    .then(
      ([
        { ZoneContextManager },
        { OTLPTraceExporter },
        { registerInstrumentations },
        { FetchInstrumentation },
        { resourceFromAttributes },
        { BatchSpanProcessor, WebTracerProvider },
        { W3CTraceContextPropagator },
      ]) => {
        const provider = new WebTracerProvider({
          resource: resourceFromAttributes({ "service.name": serviceName }),
          spanProcessors: [new BatchSpanProcessor(new OTLPTraceExporter({ url: exportUrl }))],
        });
        // ZoneContextManager keeps the active span across async boundaries, so a ui.*
        // span stays the parent of the fetch it triggers. The propagator MUST be set
        // explicitly: in a browser bundle register() can't build it from env vars, so
        // without this no `traceparent` is injected into /api calls and the backend
        // starts a separate trace (no end-to-end linkage).
        provider.register({
          contextManager: new ZoneContextManager(),
          propagator: new W3CTraceContextPropagator(),
        });
        // Only fetch instrumentation: each browser API call becomes a clean
        // "METHOD /path" span that propagates into the backend. Document-load is
        // omitted on purpose — its documentFetch/resourceFetch spans (every JS/CSS/
        // image) are page-load noise, not the request traces we care about.
        registerInstrumentations({
          instrumentations: [
            new FetchInstrumentation({
              ignoreUrls: [/\/otlp\//],
              propagateTraceHeaderCorsUrls: [/\/api\//],
              applyCustomAttributesOnSpan: (span, request, result) => {
                // Rename the default "HTTP GET" span to "GET /path" so browser spans
                // read like the backend ones.
                try {
                  const method =
                    (request && typeof request === "object" && "method" in request
                      ? (request as RequestInit).method
                      : undefined) ?? "GET";
                  const href =
                    result && "url" in result && (result as Response).url
                      ? (result as Response).url
                      : undefined;
                  if (href) {
                    const path = new URL(href, window.location.origin).pathname;
                    (span as { updateName?: (n: string) => void }).updateName?.(`${method} ${path}`);
                  }
                } catch {
                  /* naming is best-effort */
                }
                // Keep search terms out of Tempo. FetchInstrumentation puts the whole
                // request URL on the span, so /streams/all/entries?q=… would export a
                // reader's query even though the API scrubs its own span and its access
                // log. This hook runs on the failure path too, before the span ends and
                // while its attributes are still writable.
                scrubQueryString(span);
              },
            }),
          ],
        });
      },
    )
    .catch(() => {
      // Telemetry must never break the app.
    });
}
