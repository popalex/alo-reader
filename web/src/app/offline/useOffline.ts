// React seams over the offline queue (WP-14): online/offline status, the queued
// count for the badge, and the replay driver that fires on reconnect.

import { useEffect } from "react";
import { useSyncExternalStore } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { postEntryState } from "../../api/endpoints";
import { useTokenGetter } from "../auth";
import { queryKeys } from "../../api/queries";
import { getQueuedCount, refreshQueuedCount, replayQueue, subscribeQueue } from "./queue";
import { pushToast } from "../toast";

/** How often to retry a stuck queue when no `online` event is coming. */
const RETRY_INTERVAL_MS = 30_000;

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
      const dropped = await replayQueue(async (item) => {
        await postEntryState(await getToken(), item);
      });
      if (dropped > 0 && !cancelled) {
        pushToast(
          dropped === 1
            ? "One offline change couldn't be saved and was discarded."
            : `${dropped} offline changes couldn't be saved and were discarded.`,
          "error",
        );
      }
      if (!cancelled) {
        await qc.invalidateQueries({ queryKey: queryKeys.counts });
        await qc.invalidateQueries({ queryKey: ["entries"] });
      }
    };

    void refreshQueuedCount();
    void drain(); // in case the queue survived a reload and we're already online
    const onOnline = () => void drain();
    window.addEventListener("online", onOnline);
    // navigator.onLine means "an interface exists", not "the server is reachable", so
    // the common failure (flaky wifi, server restarting) queues a change without ever
    // firing an `online` event to drain it. Without this the badge sits at >= 1 and
    // the change waits for a page reload.
    const timer = window.setInterval(() => {
      if (getQueuedCount() > 0) void drain();
    }, RETRY_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener("online", onOnline);
    };
  }, [getToken, qc]);
}
