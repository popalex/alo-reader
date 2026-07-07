import { QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "../api/client";
import { pushToast } from "./toast";

// A fresh client per app mount (see AppProviders) so tests don't share cache.
export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error) => {
        const message =
          error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
        pushToast(message, "error");
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: 1,
        // WP-11 owns refetch-on-focus explicitly; keep it off until then.
        refetchOnWindowFocus: false,
      },
    },
  });
}
