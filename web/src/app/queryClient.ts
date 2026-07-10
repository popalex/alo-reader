import { QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "../api/client";
import { pushToast } from "./toast";

// A fresh client per app mount (see AppProviders) so tests don't share cache.
export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error) => {
        // Offline, uncached data legitimately can't load — the view shows an
        // in-place "you're offline" state, so don't also fire an alarming toast.
        if (!navigator.onLine) return;
        const message =
          error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
        pushToast(message, "error");
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: 1,
        // Refresh on focus, but respect staleTime — TanStack won't refetch data
        // newer than 30s (WP-11). The manual refresh button force-invalidates.
        refetchOnWindowFocus: true,
        // The service worker owns offline caching (WP-14), so don't let TanStack
        // pause queries when offline — run the queryFn and let the SW serve cache.
        networkMode: "always",
      },
      mutations: {
        // Critical for the offline queue: with the default "online" mode TanStack
        // pauses mutations offline and never calls mutationFn, so our enqueue never
        // runs. "always" lets mutationFn run and decide (post or enqueue).
        networkMode: "always",
      },
    },
  });
}
