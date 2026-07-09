// React seams over the offline queue (WP-14): online/offline status, the queued
// count for the badge, and the replay driver that fires on reconnect.

import { useEffect } from "react";
import { useSyncExternalStore } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { postEntryState } from "../../api/endpoints";
import { useTokenGetter } from "../auth";
import { queryKeys } from "../../api/queries";
import { getQueuedCount, refreshQueuedCount, replayQueue, subscribeQueue } from "./queue";

function subscribeOnline(cb: () => void): () => void {
  window.addEventListener("online", cb);
  window.addEventListener("offline", cb);
  return () => {
    window.removeEventListener("online", cb);
    window.removeEventListener("offline", cb);
  };
}

/** Live online/offline status. */
export function useOnline(): boolean {
  return useSyncExternalStore(
    subscribeOnline,
    () => navigator.onLine,
    () => true, // SSR/first paint: assume online
  );
}

/** Number of mutations waiting to replay (drives the badge). */
export function useQueuedCount(): number {
  return useSyncExternalStore(subscribeQueue, getQueuedCount, () => 0);
}

/** Mount once (AppProviders): load the queued count, and replay the outbox on
 *  reconnect and at startup. After a drain, reconcile counts with the server. */
export function useOfflineReplay(): void {
  const getToken = useTokenGetter();
  const qc = useQueryClient();

  useEffect(() => {
    let cancelled = false;
    const drain = async () => {
      await replayQueue(async (item) => {
        await postEntryState(await getToken(), item);
      });
      if (!cancelled) {
        await qc.invalidateQueries({ queryKey: queryKeys.counts });
        await qc.invalidateQueries({ queryKey: ["entries"] });
      }
    };

    void refreshQueuedCount();
    void drain(); // in case the queue survived a reload and we're already online
    const onOnline = () => void drain();
    window.addEventListener("online", onOnline);
    return () => {
      cancelled = true;
      window.removeEventListener("online", onOnline);
    };
  }, [getToken, qc]);
}
