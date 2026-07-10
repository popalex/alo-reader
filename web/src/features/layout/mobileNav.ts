// Lets the list's top-bar hamburger (deep under the router Outlet) open the feeds
// drawer that AppLayout owns. Kept JSX-free so it stays HMR-safe.

import { createContext, useContext } from "react";

interface MobileNavApi {
  openSidebar: () => void;
}

export const MobileNavContext = createContext<MobileNavApi>({ openSidebar: () => {} });

export function useMobileNav(): MobileNavApi {
  return useContext(MobileNavContext);
}
