// TanStack Query hooks over the typed endpoints. Query functions resolve the
// bearer token through the auth seam, so components never touch it.

import { useQuery } from "@tanstack/react-query";

import { useTokenGetter } from "../app/auth";
import { getCounts, getFolders, getSubscriptions } from "./endpoints";

export const queryKeys = {
  folders: ["folders"] as const,
  subscriptions: ["subscriptions"] as const,
  counts: ["counts"] as const,
};

export function useFolders() {
  const getToken = useTokenGetter();
  return useQuery({
    queryKey: queryKeys.folders,
    queryFn: async () => getFolders(await getToken()),
  });
}

export function useSubscriptions() {
  const getToken = useTokenGetter();
  return useQuery({
    queryKey: queryKeys.subscriptions,
    queryFn: async () => getSubscriptions(await getToken()),
  });
}

export function useCounts() {
  const getToken = useTokenGetter();
  return useQuery({
    queryKey: queryKeys.counts,
    queryFn: async () => getCounts(await getToken()),
  });
}
