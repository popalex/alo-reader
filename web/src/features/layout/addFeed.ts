// Opens the app-wide add-feed dialog that AppLayout owns. The welcome screen uses it:
// adding the first feed swaps that screen for the article list, and a page change
// remounts the stream view, so a dialog owned by either would close mid-use. Kept
// JSX-free so it stays HMR-safe, like mobileNav.ts.

import { createContext, useContext } from "react";

interface AddFeedApi {
  openAddFeed: () => void;
}

export const AddFeedContext = createContext<AddFeedApi>({ openAddFeed: () => {} });

export function useAddFeed(): AddFeedApi {
  return useContext(AddFeedContext);
}
