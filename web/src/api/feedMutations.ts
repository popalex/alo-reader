// Feed-management mutations: subscribe to a new feed and import an OPML file.
// Most of these skip the optimistic cache surgery the read/star mutations do,
// because a new or deleted subscription changes folders, subscriptions and counts
// all at once; on success we invalidate those three queries and let them refetch.
// The two renames are the exception. Each changes one string on one row, the
// client already knows the new value, and the inline editor closes the moment you
// hit Enter, so waiting for the refetch would show the old name back.

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
  type Folder,
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

/** Rename a category. This one *does* patch the cache: a rename changes a single
 *  string on a single row, so there is nothing to re-derive. Without the patch the
 *  sidebar keeps the old name for the whole PATCH + refetch round trip, and the
 *  inline editor has already closed by then, so the edit looks like it was dropped. */
export function useUpdateFolder() {
  const getToken = useTokenGetter();
  const qc = useQueryClient();
  const refresh = useRefreshFeedLists();
  return useMutation({
    mutationFn: async (vars: { id: number; name: string }) =>
      updateFolder(await getToken(), vars.id, vars.name),
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: queryKeys.folders });
      const prevFolders = qc.getQueryData<Folder[]>(queryKeys.folders);
      qc.setQueryData<Folder[]>(queryKeys.folders, (folders) =>
        folders?.map((f) => (f.id === vars.id ? { ...f, name: vars.name } : f)),
      );
      return { prevFolders };
    },
    onSuccess: () => refresh(),
    onError: (_err, _vars, ctx) => {
      qc.setQueryData(queryKeys.folders, ctx?.prevFolders);
      pushToast("Couldn't rename the category.", "error");
    },
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
  const qc = useQueryClient();
  const refresh = useRefreshFeedLists();
  return useMutation({
    mutationFn: async (vars: { id: number } & UpdateSubscriptionInput): Promise<Subscription> => {
      const { id, ...input } = vars;
      return updateSubscription(await getToken(), id, input);
    },
    onMutate: async (vars) => {
      // Same reasoning as useUpdateFolder, but only for a title the client can
      // predict. Clearing the override (null/"") falls back to the feed's own
      // title, which lives on the server, and a folder_id move regroups the whole
      // sidebar — both are left to the refetch.
      const title = vars.title_override;
      if (!title) return { prevSubs: undefined };
      await qc.cancelQueries({ queryKey: queryKeys.subscriptions });
      const prevSubs = qc.getQueryData<Subscription[]>(queryKeys.subscriptions);
      qc.setQueryData<Subscription[]>(queryKeys.subscriptions, (subs) =>
        subs?.map((s) => (s.id === vars.id ? { ...s, title } : s)),
      );
      return { prevSubs };
    },
    onSuccess: () => refresh(),
    onError: (_err, _vars, ctx) => {
      if (ctx?.prevSubs) qc.setQueryData(queryKeys.subscriptions, ctx.prevSubs);
      pushToast("Couldn't save the feed's settings.", "error");
    },
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
