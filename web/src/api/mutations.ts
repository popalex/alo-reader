// Read/star mutations with optimistic cache updates and rollback (DESIGN.md §5).
// Changes are applied immediately to every cached entries stream and to the
// unread counts; on error the pre-mutation snapshot is restored and a toast
// fires. Counts stay exact for single flips (no refetch flash); mark-all-read
// reconciles counts from the server on settle (unloaded entries also change).

import {
  useMutation,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from "@tanstack/react-query";

import { useTokenGetter } from "../app/auth";
import { pushToast } from "../app/toast";
import { streamToPath, type StreamDescriptor } from "../lib/streams";
import {
  postEntryState,
  postMarkRead,
  type Counts,
  type EntryDetail,
  type EntryListItem,
  type StreamPage,
  type Subscription,
} from "./endpoints";
import { queryKeys } from "./queries";

type EntriesData = InfiniteData<StreamPage>;
type EntriesSnapshot = Array<[readonly unknown[], EntriesData | undefined]>;

function subIdForFeed(subs: Subscription[] | undefined, feedId: number): number | undefined {
  return subs?.find((s) => s.feed_id === feedId)?.id;
}

/** Patch matching entries in every cached ["entries", …] stream. */
function patchEntries(qc: QueryClient, ids: ReadonlySet<number>, patch: Partial<EntryListItem>): void {
  qc.setQueriesData<EntriesData>({ queryKey: ["entries"] }, (data) => {
    if (!data) return data;
    let changed = false;
    const pages = data.pages.map((page) => ({
      ...page,
      entries: page.entries.map((e) => {
        if (!ids.has(e.id)) return e;
        changed = true;
        return { ...e, ...patch };
      }),
    }));
    return changed ? { ...data, pages } : data;
  });
}

function adjustCounts(qc: QueryClient, perSubDelta: Map<number, number>, totalDelta: number): void {
  if (totalDelta === 0 && perSubDelta.size === 0) return;
  qc.setQueryData<Counts>(queryKeys.counts, (c) => {
    if (!c) return c;
    return {
      total_unread: Math.max(0, c.total_unread + totalDelta),
      subscriptions: c.subscriptions.map((s) =>
        perSubDelta.has(s.id) ? { ...s, unread: Math.max(0, s.unread + (perSubDelta.get(s.id) ?? 0)) } : s,
      ),
    };
  });
}

function restoreEntries(qc: QueryClient, snapshot: EntriesSnapshot | undefined): void {
  if (!snapshot) return;
  for (const [key, data] of snapshot) qc.setQueryData(key, data);
}

export function useSetEntryState() {
  const getToken = useTokenGetter();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { ids: number[]; read?: boolean; starred?: boolean }) =>
      postEntryState(await getToken(), { ...vars, changed_at: new Date().toISOString() }),
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: ["entries"] });
      await qc.cancelQueries({ queryKey: queryKeys.counts });
      const prevEntries = qc.getQueriesData<EntriesData>({ queryKey: ["entries"] });
      const prevCounts = qc.getQueryData<Counts>(queryKeys.counts);
      const subs = qc.getQueryData<Subscription[]>(queryKeys.subscriptions);

      // Current read-state + feed for each id (to compute count deltas).
      const info = new Map<number, { feedId: number; wasRead: boolean }>();
      for (const [, data] of prevEntries) {
        if (!data) continue;
        for (const page of data.pages)
          for (const e of page.entries)
            if (!info.has(e.id)) info.set(e.id, { feedId: e.feed_id, wasRead: e.is_read });
      }

      const patch: Partial<EntryListItem> = {};
      if (vars.read !== undefined) patch.is_read = vars.read;
      if (vars.starred !== undefined) patch.is_starred = vars.starred;
      patchEntries(qc, new Set(vars.ids), patch);

      // Also patch any open entry-detail caches so the reader flips instantly.
      const detailPatch: Partial<EntryDetail> = {};
      if (vars.read !== undefined) detailPatch.is_read = vars.read;
      if (vars.starred !== undefined) detailPatch.is_starred = vars.starred;
      const prevDetails: Array<[number, EntryDetail | undefined]> = vars.ids.map((id) => [
        id,
        qc.getQueryData<EntryDetail>(["entry", id]),
      ]);
      for (const id of vars.ids) {
        qc.setQueryData<EntryDetail>(["entry", id], (d) => (d ? { ...d, ...detailPatch } : d));
      }

      if (vars.read !== undefined) {
        const perSub = new Map<number, number>();
        let total = 0;
        for (const id of vars.ids) {
          const i = info.get(id);
          if (!i) continue;
          const delta = vars.read ? (i.wasRead ? 0 : -1) : i.wasRead ? 1 : 0;
          if (!delta) continue;
          total += delta;
          const sid = subIdForFeed(subs, i.feedId);
          if (sid != null) perSub.set(sid, (perSub.get(sid) ?? 0) + delta);
        }
        adjustCounts(qc, perSub, total);
      }
      return { prevEntries, prevCounts, prevDetails };
    },
    onError: (_err, _vars, ctx) => {
      restoreEntries(qc, ctx?.prevEntries);
      qc.setQueryData(queryKeys.counts, ctx?.prevCounts);
      for (const [id, d] of ctx?.prevDetails ?? []) qc.setQueryData(["entry", id], d);
      pushToast("Couldn't save your change — it was rolled back.", "error");
    },
    onSettled: (_data, _err, vars) => {
      // A star toggle can change membership of the starred stream.
      if (vars.starred !== undefined) void qc.invalidateQueries({ queryKey: ["entries", "starred"] });
    },
  });
}

export function useMarkStreamRead(stream: StreamDescriptor) {
  const getToken = useTokenGetter();
  const qc = useQueryClient();
  const path = streamToPath(stream);
  return useMutation({
    mutationFn: async (maxEntryId: number) => postMarkRead(await getToken(), path, maxEntryId),
    onMutate: async (maxEntryId) => {
      await qc.cancelQueries({ queryKey: ["entries"] });
      await qc.cancelQueries({ queryKey: queryKeys.counts });
      const prevEntries = qc.getQueriesData<EntriesData>({ queryKey: ["entries"] });
      const prevCounts = qc.getQueryData<Counts>(queryKeys.counts);
      const subs = qc.getQueryData<Subscription[]>(queryKeys.subscriptions);

      const streamData =
        qc.getQueryData<EntriesData>(["entries", path, "all"]) ??
        qc.getQueryData<EntriesData>(["entries", path, "unread"]);
      const affected = new Set<number>();
      const perSub = new Map<number, number>();
      let total = 0;
      if (streamData) {
        for (const page of streamData.pages)
          for (const e of page.entries)
            if (e.id <= maxEntryId && !e.is_read) {
              affected.add(e.id);
              total -= 1;
              const sid = subIdForFeed(subs, e.feed_id);
              if (sid != null) perSub.set(sid, (perSub.get(sid) ?? 0) - 1);
            }
      }
      patchEntries(qc, affected, { is_read: true });
      adjustCounts(qc, perSub, total);
      return { prevEntries, prevCounts };
    },
    onError: (_err, _vars, ctx) => {
      restoreEntries(qc, ctx?.prevEntries);
      qc.setQueryData(queryKeys.counts, ctx?.prevCounts);
      pushToast("Couldn't mark all read — it was rolled back.", "error");
    },
    // Entries below the loaded window also got marked read — reconcile counts.
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.counts });
    },
  });
}
