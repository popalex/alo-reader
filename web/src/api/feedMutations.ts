// Feed-management mutations: subscribe to a new feed and import an OPML file.
// Unlike the read/star mutations these don't do optimistic cache surgery — a new
// subscription changes folders, subscriptions and counts all at once, so on
// success we just invalidate those three queries and let them refetch.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useTokenGetter } from "../app/auth";
import { pushToast } from "../app/toast";
import {
  createSubscription,
  deleteFolder,
  deleteSubscription,
  importOpml,
  updateFolder,
  updateSubscription,
  type CreateSubscriptionInput,
  type ImportReport,
  type Subscription,
  type UpdateSubscriptionInput,
} from "./endpoints";
import { queryKeys } from "./queries";

/** Invalidate the feed-list queries after a change. A just-added feed's real title +
 *  articles then keep filling in via usePendingFeedPolling (which polls while any feed
 *  is unfetched), so no delayed refetch is needed here. */
function useRefreshFeedLists(): () => void {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: queryKeys.subscriptions });
    void qc.invalidateQueries({ queryKey: queryKeys.folders });
    void qc.invalidateQueries({ queryKey: queryKeys.counts });
  };
}

export function useCreateSubscription() {
  const getToken = useTokenGetter();
  const refresh = useRefreshFeedLists();
  return useMutation({
    mutationFn: async (input: CreateSubscriptionInput): Promise<Subscription> =>
      createSubscription(await getToken(), input),
    onSuccess: (sub) => {
      refresh();
      pushToast(`Subscribed to ${sub.title || "the feed"}.`, "info");
    },
  });
}

export function useUpdateFolder() {
  const getToken = useTokenGetter();
  const refresh = useRefreshFeedLists();
  return useMutation({
    mutationFn: async (vars: { id: number; name: string }) =>
      updateFolder(await getToken(), vars.id, vars.name),
    onSuccess: () => refresh(),
    onError: () => pushToast("Couldn't rename the category.", "error"),
  });
}

export function useDeleteFolder() {
  const getToken = useTokenGetter();
  const refresh = useRefreshFeedLists();
  return useMutation({
    mutationFn: async (id: number) => deleteFolder(await getToken(), id),
    onSuccess: () => {
      // refresh() re-fetches subscriptions too, so feeds now show under Uncategorized.
      refresh();
      pushToast("Category deleted.", "info");
    },
    onError: () => pushToast("Couldn't delete the category.", "error"),
  });
}

export function useUpdateSubscription() {
  const getToken = useTokenGetter();
  const refresh = useRefreshFeedLists();
  return useMutation({
    mutationFn: async (vars: { id: number } & UpdateSubscriptionInput): Promise<Subscription> => {
      const { id, ...input } = vars;
      return updateSubscription(await getToken(), id, input);
    },
    onSuccess: () => refresh(),
    onError: () => pushToast("Couldn't save the feed's settings.", "error"),
  });
}

export function useDeleteSubscription() {
  const getToken = useTokenGetter();
  const qc = useQueryClient();
  const refresh = useRefreshFeedLists();
  return useMutation({
    mutationFn: async (vars: { id: number; title?: string }): Promise<void> =>
      deleteSubscription(await getToken(), vars.id),
    onSuccess: (_data, vars) => {
      refresh();
      // Drop the unsubscribed feed's entries from every cached stream (e.g. All).
      void qc.invalidateQueries({ queryKey: ["entries"] });
      pushToast(`Unsubscribed from ${vars.title || "the feed"}.`, "info");
    },
    onError: () => pushToast("Couldn't unsubscribe — try again.", "error"),
  });
}

export function useImportOpml() {
  const getToken = useTokenGetter();
  const refresh = useRefreshFeedLists();
  return useMutation({
    mutationFn: async (file: File): Promise<ImportReport> => importOpml(await getToken(), file),
    onSuccess: (report) => {
      refresh();
      const n = report.imported;
      pushToast(`Imported ${n} feed${n === 1 ? "" : "s"}.`, "info");
    },
  });
}
