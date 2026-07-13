// TanStack Query hooks over the typed endpoints. Query functions resolve the
// bearer token through the auth seam, so components never touch it.

import { useCallback, useEffect, useMemo, useRef } from "react";

import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";

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

/** While any subscribed feed hasn't been polled yet (no last_fetched_at, no error),
 *  refetch the lightweight feed list + counts on a short interval so its title and
 *  unread count appear on their own once the worker fetches it — no manual refresh.
 *  Entries are refetched only when a feed actually finishes its first fetch, so the
 *  stream the user is reading isn't churned every tick. Stops when nothing is
 *  pending (or after a safety cap). */
export function usePendingFeedPolling(): void {
  const qc = useQueryClient();
  const subs = useSubscriptions();
  const subsData = subs.data;
  const pendingIds = useMemo(
    () =>
      new Set(
        (subsData ?? [])
          .filter((s) => !s.last_fetched_at && !s.last_error)
          .map((s) => s.feed_id),
      ),
    [subsData],
  );
  const pending = pendingIds.size > 0;

  useEffect(() => {
    if (!pending) return;
    const startedAt = Date.now();
    const id = window.setInterval(() => {
      if (Date.now() - startedAt > 90_000) {
        window.clearInterval(id);
        return;
      }
      void qc.invalidateQueries({ queryKey: queryKeys.subscriptions });
      void qc.invalidateQueries({ queryKey: queryKeys.counts });
    }, 2500);
    return () => window.clearInterval(id);
  }, [pending, qc]);

  // Refetch entries once, only when a previously-pending feed gains its first
  // last_fetched_at (its articles just landed) — not on every poll.
  const prevPending = useRef(pendingIds);
  useEffect(() => {
    const prev = prevPending.current;
    prevPending.current = pendingIds;
    const settled = (subsData ?? []).some((s) => prev.has(s.feed_id) && s.last_fetched_at);
    if (settled) void qc.invalidateQueries({ queryKey: ["entries"] });
  }, [pendingIds, subsData, qc]);
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

/** Warm an entry's detail into cache (same key/fn as useEntry). Prefetching the
 *  top of a stream while online means the service worker caches those bodies, so
 *  they open offline without having been read first. No-op on already-fresh ids. */
export function usePrefetchEntry(): (id: number) => void {
  const getToken = useTokenGetter();
  const qc = useQueryClient();
  return useCallback(
    (id) =>
      void qc.prefetchQuery({
        queryKey: ["entry", id],
        queryFn: async () => getEntry(await getToken(), id),
        staleTime: 5 * 60_000,
      }),
    [getToken, qc],
  );
}
