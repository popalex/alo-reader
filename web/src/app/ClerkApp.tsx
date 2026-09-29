// Clerk-mode shell, loaded lazily (separate chunk) only when the server's
// /config says auth_mode=clerk — none-mode users never download Clerk code.

import { ClerkProvider, Show, SignIn, UserButton, useAuth } from "@clerk/react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { AppProviders } from "./AppProviders";
import { SignedOutShell } from "./SignedOutShell";
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

// Clerk's components drawn in the app's tokens. The values must be real colours, not
// var(--accent): Clerk derives hover and pressed shades by colour maths, and with a CSS
// variable its primary button came out invisible. So the tokens are read as computed,
// and read again whenever the theme changes (the toggle sets data-theme on <html>;
// "system" follows the OS preference).
const TOKENS = {
  colorPrimary: "--accent",
  colorPrimaryForeground: "--accent-contrast",
  colorBackground: "--surface",
  colorForeground: "--text",
  colorMutedForeground: "--text-dim",
  colorInput: "--bg",
  colorInputForeground: "--text",
  colorBorder: "--border",
  colorNeutral: "--text",
  fontFamily: "--font-sans",
  borderRadius: "--radius-sm",
} as const;

function readTokens(): Record<keyof typeof TOKENS, string> {
  const css = getComputedStyle(document.documentElement);
  return Object.fromEntries(
    Object.entries(TOKENS).map(([key, name]) => [key, css.getPropertyValue(name).trim()]),
  ) as Record<keyof typeof TOKENS, string>;
}

function useClerkAppearance() {
  const [colors, setColors] = useState(readTokens);
  useEffect(() => {
    const refresh = () => setColors(readTokens());
    const observer = new MutationObserver(refresh);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const scheme = window.matchMedia("(prefers-color-scheme: dark)");
    scheme.addEventListener("change", refresh);
    return () => {
      observer.disconnect();
      scheme.removeEventListener("change", refresh);
    };
  }, []);
  return useMemo(
    () => ({
      variables: { ...colors },
      elements: {
        // The signed-out shell already frames the form, and has its own heading.
        cardBox: { boxShadow: "none", border: `1px solid ${colors.colorBorder}` },
        header: { display: "none" },
      },
    }),
    [colors],
  );
}

export default function ClerkApp({ publishableKey }: { publishableKey: string }) {
  const appearance = useClerkAppearance();
  return (
    <ClerkProvider
      publishableKey={publishableKey}
      appearance={appearance}
      // Clerk's default is "/", which since the app moved to /app/ is the landing
      // page: a successful sign-in dropped the user on marketing copy. Signing out
      // does go to the landing page, on purpose.
      signInFallbackRedirectUrl={import.meta.env.BASE_URL}
      signUpFallbackRedirectUrl={import.meta.env.BASE_URL}
      afterSignOutUrl="/"
    >
      <Show when="signed-out">
        <SignedOutShell>
          <SignIn />
        </SignedOutShell>
      </Show>
      <Show when="signed-in">
        <header style={{ display: "flex", justifyContent: "flex-end", padding: "0.5rem 1rem" }}>
          <UserButton />
        </header>
        <ClerkTokenBridge>
          <AppProviders />
        </ClerkTokenBridge>
      </Show>
    </ClerkProvider>
  );
}
