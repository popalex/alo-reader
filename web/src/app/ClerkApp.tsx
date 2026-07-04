// Clerk-mode shell, loaded lazily (separate chunk) only when the server's
// /config says auth_mode=clerk — none-mode users never download Clerk code.

import {
  ClerkProvider,
  SignedIn,
  SignedOut,
  SignIn,
  UserButton,
  useAuth,
} from "@clerk/clerk-react";
import { useCallback, useRef, type ReactNode } from "react";

import { Home } from "../features/Home";
import { TokenProvider, type TokenGetter } from "./auth";

/** Bridges Clerk's session (auto-refreshing) into the app's token seam. */
function ClerkTokenBridge({ children }: { children: ReactNode }) {
  const { getToken } = useAuth();
  const latest = useRef(getToken);
  latest.current = getToken;
  // Stable identity so consumers' effects don't re-run every render.
  const stableGetToken: TokenGetter = useCallback(() => latest.current(), []);
  return <TokenProvider value={stableGetToken}>{children}</TokenProvider>;
}

export default function ClerkApp({ publishableKey }: { publishableKey: string }) {
  return (
    <ClerkProvider publishableKey={publishableKey}>
      <SignedOut>
        <main style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
          <SignIn />
        </main>
      </SignedOut>
      <SignedIn>
        <header style={{ display: "flex", justifyContent: "flex-end", padding: "0.5rem 1rem" }}>
          <UserButton />
        </header>
        <ClerkTokenBridge>
          <Home />
        </ClerkTokenBridge>
      </SignedIn>
    </ClerkProvider>
  );
}
