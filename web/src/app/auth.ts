// Frontend auth seam, mirroring the backend's AuthProvider: components ask for
// a bearer token through this context and never know which mode supplied it.
// Default (AUTH_MODE=none): no token — requests go out bare and the backend
// maps them to the single local user. Clerk mode overrides it in ClerkApp.

import { createContext, useContext } from "react";

export type TokenGetter = () => Promise<string | null>;

const noToken: TokenGetter = () => Promise.resolve(null);

const TokenContext = createContext<TokenGetter>(noToken);

export const TokenProvider = TokenContext.Provider;

export function useTokenGetter(): TokenGetter {
  return useContext(TokenContext);
}
