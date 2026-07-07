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

function BootError({ message }: { message: string }) {
  return (
    <main style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
      <p role="alert">Could not start alo-reader — {message}</p>
    </main>
  );
}

export function App() {
  const [config, setConfig] = useState<ApiConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getConfig()
      .then((c) => {
        if (!cancelled) setConfig(c);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? `${err.code}: ${err.message}` : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <BootError message={error} />;
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
