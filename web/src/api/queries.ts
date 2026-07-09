// TanStack Query hooks over the typed endpoints. Query functions resolve the
// bearer token through the auth seam, so components never touch it.

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { useTokenGetter } from "../app/auth";
import { streamToPath, type StreamDescriptor } from "../lib/streams";
import {
  getCounts,
  getEntry,
  getFolders,
  getStreamEntries,
  getSubscriptions,
} from "./endpoints";

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

export type StreamStatus = "unread" | "all";

export function useStreamEntries(
  stream: StreamDescriptor,
  status: StreamStatus = "all",
  q?: string,
) {
  const getToken = useTokenGetter();
  const path = streamToPath(stream);
  return useInfiniteQuery({
    // q is part of the key so a query switches result sets (and mutations still
    // match the ["entries", …] prefix, so optimistic patches reach search rows too).
    queryKey: ["entries", path, status, q ?? null],
    queryFn: async ({ pageParam }) =>
      getStreamEntries(await getToken(), path, { status, cursor: pageParam, q }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });
}

export function useEntry(id: number | null) {
  const getToken = useTokenGetter();
  return useQuery({
    queryKey: ["entry", id],
    queryFn: async () => getEntry(await getToken(), id as number),
    enabled: id != null,
  });
}
