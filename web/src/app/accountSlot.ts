// The account control (Clerk's user button) for the sidebar footer. The app shell
// knows nothing about Clerk, and Clerk code only loads in clerk mode, so ClerkApp
// hands the element down through this context; in AUTH_MODE=none it stays null and
// the footer leaves it out. JSX-free, so it stays HMR-safe.

import { createContext, useContext, type ReactNode } from "react";

export const AccountSlotContext = createContext<ReactNode>(null);

export function useAccountSlot(): ReactNode {
  return useContext(AccountSlotContext);
}
