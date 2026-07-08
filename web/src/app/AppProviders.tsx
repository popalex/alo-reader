// The authenticated app root, shared by both auth modes: none-mode renders it
// directly (bare requests), clerk-mode renders it inside the Clerk shell after
// sign-in (token seam supplied). Owns the query cache, the router, and the
// toast surface. A fresh QueryClient per mount keeps tests isolated.

import { useState } from "react";

import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";

import { createQueryClient } from "./queryClient";
import { router } from "./router";
import { Toaster } from "./Toaster";

export function AppProviders() {
  const [queryClient] = useState(createQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>
  );
}
