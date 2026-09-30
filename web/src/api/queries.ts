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

const PENDING_POLL_GIVE_UP_MS = 10 * 60_000;

/** How long to wait before the next check of not-yet-fetched feeds, given how long
 *  they have been pending: quickly at first, then at a pace that costs nothing. */
export function pendingPollDelay(elapsedMs: number): number {
  return elapsedMs < 90_000 ? 2500 : 30_000;
}

/** While any subscribed feed hasn't been polled yet (no last_fetched_at, no error),
 *  refetch the lightweight feed list + counts on a short interval so its title and
 *  unread count appear on their own once the worker fetches it — no manual refresh.
 *  Entries are refetched only when a feed actually finishes its first fetch, so the
 *  stream the user is reading isn't churned every tick. Polls every 2.5 s for the
 *  first 90 s, when a new feed usually lands, then every 30 s, and stops when nothing
 *  is pending or after 10 minutes. Stopping at 90 s left a feed that took longer
 *  (a slow site, a busy worker) looking empty, under "Fetching your feeds", until a
 *  reload. */
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
  // Key the effect on WHICH feeds are pending, not merely whether any are. With a
  // boolean, a feed added after the give-up cap stopped the polling never starts
  // a new one — the boolean is still true — so its title, entries and unread count
  // never arrive until the user reloads.
  const pendingKey = useMemo(() => [...pendingIds].sort((a, b) => a - b).join(","), [pendingIds]);

  useEffect(() => {
    if (!pendingKey) return;
    const startedAt = Date.now();
    let timer = 0;
    const tick = () => {
      const elapsed = Date.now() - startedAt;
      if (elapsed > PENDING_POLL_GIVE_UP_MS) return;
      void qc.invalidateQueries({ queryKey: queryKeys.subscriptions });
      void qc.invalidateQueries({ queryKey: queryKeys.counts });
      timer = window.setTimeout(tick, pendingPollDelay(elapsed));
    };
    timer = window.setTimeout(tick, pendingPollDelay(0));
    return () => window.clearTimeout(timer);
  }, [pendingKey, qc]);

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

export function useStreamEntries(stream: StreamDescriptor, q?: string) {
  const getToken = useTokenGetter();
  const path = streamToPath(stream);
  return useInfiniteQuery({
    // q is part of the key so a query switches result sets (and mutations still
    // match the ["entries", …] prefix, so optimistic patches reach search rows too).
    queryKey: ["entries", path, q ?? null],
    queryFn: async ({ pageParam }) =>
      getStreamEntries(await getToken(), path, { cursor: pageParam, q }),
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
