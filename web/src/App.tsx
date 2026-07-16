// Boot sequence (DESIGN.md §0.1): fetch /config, then branch on auth_mode.
//   none  → render the app directly; requests go out bare (no token) and the
//           backend maps them to the single local user. Clerk code is never
//           downloaded in this mode.
//   clerk → lazy-load the Clerk shell as a separate chunk, handing it the
//           server-supplied publishable key.

import { Suspense, lazy, useEffect, useState } from "react";

import { ApiError, getConfig, type ApiConfig } from "./api/client";
import { AppProviders } from "./app/AppProviders";

const ClerkApp = lazy(() => import("./app/ClerkApp"));

function Booting() {
  return (
    <main style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
      <p>Loading…</p>
    </main>
  );
}

function BootError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <main style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
      <div style={{ display: "grid", placeItems: "center", gap: 12, textAlign: "center" }}>
        <p role="alert">Could not start alo-reader — {message}</p>
        {onRetry ? (
          <button type="button" onClick={onRetry}>
            Try again
          </button>
        ) : null}
      </div>
    </main>
  );
}

export function App() {
  const [config, setConfig] = useState<ApiConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getConfig()
      .then((c) => {
        if (cancelled) return;
        // Turn on browser tracing before the app renders so document-load + the first
        // API calls are captured (lazy-loads the OTel SDK; no-op when disabled).
        if (c.otel_enabled && c.otel_traces_url) {
          void import("./app/telemetry").then((t) =>
            t.initBrowserTelemetry({ serviceName: "alo-web", exportUrl: c.otel_traces_url! }),
          );
        }
        setConfig(c);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? `${err.code}: ${err.message}` : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // A failed /config fetch (transient network blip on first load) is otherwise a
  // dead end — let the user retry without a full reload.
  const retry = () => {
    setError(null);
    setAttempt((n) => n + 1);
  };

  if (error) return <BootError message={error} onRetry={retry} />;
  if (!config) return <Booting />;

  if (config.auth_mode === "clerk") {
    if (!config.clerk_publishable_key) {
      return <BootError message="clerk mode is configured but no publishable key was provided" />;
    }
    return (
      <Suspense fallback={<Booting />}>
        <ClerkApp publishableKey={config.clerk_publishable_key} />
      </Suspense>
    );
  }

  // none (and any non-clerk) mode: no token seam needed — the default
  // TokenGetter resolves to null, so requests go out bare.
  return <AppProviders />;
}
