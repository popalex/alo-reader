// Opens the app-wide feed settings flow (FeedSettingsFlow) that AppLayout owns: the
// sidebar's gear and the list's "failing feed" banner both use it. It used to live in
// the sidebar, which on a phone exists only while the drawer is open, so nothing
// outside the sidebar could open it. JSX-free, so it stays HMR-safe.

import { createContext, useContext } from "react";

import type { Subscription } from "../../api/endpoints";

interface FeedSettingsApi {
  openFeedSettings: (sub: Subscription) => void;
}

export const FeedSettingsContext = createContext<FeedSettingsApi>({ openFeedSettings: () => {} });

export function useFeedSettings(): FeedSettingsApi {
  return useContext(FeedSettingsContext);
}
