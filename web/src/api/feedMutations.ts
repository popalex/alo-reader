// Feed-management mutations: subscribe to a new feed and import an OPML file.
// Unlike the read/star mutations these don't do optimistic cache surgery — a new
// subscription changes folders, subscriptions and counts all at once, so on
// success we just invalidate those three queries and let them refetch.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useTokenGetter } from "../app/auth";
import { pushToast } from "../app/toast";
import {
  createSubscription,
  deleteSubscription,
  importOpml,
  type CreateSubscriptionInput,
  type ImportReport,
  type Subscription,
} from "./endpoints";
import { queryKeys } from "./queries";

/** Refreshers for feed-list changes. ``refresh`` invalidates the three list
 *  queries now; ``refreshAfterFetch`` also re-runs on a short delay (plus entries),
 *  because a just-added feed stays untitled/empty until the worker polls it a few
 *  seconds later — so its real title + first articles appear without a reload. */
function useFeedListRefreshers(): { refresh: () => void; refreshAfterFetch: () => void } {
  const qc = useQueryClient();
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: queryKeys.subscriptions });
    void qc.invalidateQueries({ queryKey: queryKeys.folders });
    void qc.invalidateQueries({ queryKey: queryKeys.counts });
  };
  const refreshAfterFetch = () => {
    refresh();
    const later = () => {
      refresh();
      void qc.invalidateQueries({ queryKey: ["entries"] });
    };
    setTimeout(later, 3000);
    setTimeout(later, 8000);
  };
  return { refresh, refreshAfterFetch };
}

export function useCreateSubscription() {
  const getToken = useTokenGetter();
  const { refreshAfterFetch } = useFeedListRefreshers();
  return useMutation({
    mutationFn: async (input: CreateSubscriptionInput): Promise<Subscription> =>
      createSubscription(await getToken(), input),
    onSuccess: (sub) => {
      refreshAfterFetch();
      pushToast(`Subscribed to ${sub.title || "the feed"}.`, "info");
    },
  });
}

export function useDeleteSubscription() {
  const getToken = useTokenGetter();
  const { refresh } = useFeedListRefreshers();
  return useMutation({
    mutationFn: async (vars: { id: number; title?: string }): Promise<void> =>
      deleteSubscription(await getToken(), vars.id),
    onSuccess: (_data, vars) => {
      refresh();
      pushToast(`Unsubscribed from ${vars.title || "the feed"}.`, "info");
    },
    onError: () => pushToast("Couldn't unsubscribe — try again.", "error"),
  });
}

export function useImportOpml() {
  const getToken = useTokenGetter();
  const { refreshAfterFetch } = useFeedListRefreshers();
  return useMutation({
    mutationFn: async (file: File): Promise<ImportReport> => importOpml(await getToken(), file),
    onSuccess: (report) => {
      refreshAfterFetch();
      const n = report.imported;
      pushToast(`Imported ${n} feed${n === 1 ? "" : "s"}.`, "info");
    },
  });
}
