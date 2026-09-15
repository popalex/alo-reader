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
import { enqueue } from "../app/offline/queue";
import { pushToast } from "../app/toast";
import { streamToPath, type StreamDescriptor } from "../lib/streams";
import { ApiError } from "./client";
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

export function useSetEntryState() {
  const getToken = useTokenGetter();
  const qc = useQueryClient();
  return useMutation({
    // Offline (or a network failure) queues the change to replay on reconnect and
    // resolves successfully so the optimistic update stays; a real server error
    // (ApiError) still rejects and rolls back (DESIGN §0.3 offline scope).
    mutationFn: async (vars: { ids: number[]; read?: boolean; starred?: boolean }) => {
      const payload = { ...vars, changed_at: new Date().toISOString() };
      if (!navigator.onLine) {
        await enqueue(payload);
        return { updated: payload.ids.length };
      }
      try {
        return await postEntryState(await getToken(), payload);
      } catch (err) {
        if (err instanceof ApiError) throw err; // server rejected → real failure
        await enqueue(payload); // network error → queue for replay
        return { updated: payload.ids.length };
      }
    },
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: ["entries"] });
      await qc.cancelQueries({ queryKey: queryKeys.counts });
      const prevEntries = qc.getQueriesData<EntriesData>({ queryKey: ["entries"] });
      const subs = qc.getQueryData<Subscription[]>(queryKeys.subscriptions);

      // Current read-state + feed for each id (to compute count deltas).
      const info = new Map<number, { feedId: number; wasRead: boolean }>();
      for (const [, data] of prevEntries) {
        if (!data) continue;
        for (const page of data.pages)
          for (const e of page.entries)
            if (!info.has(e.id)) info.set(e.id, { feedId: e.feed_id, wasRead: e.is_read });
      }

      // Remember what THESE ids looked like, not what the whole cache looked like.
      // Overlapping mutations are normal (a scroll marker fires one per 500-id chunk
      // while a click fires another), and restoring a global snapshot on failure
      // would undo whatever a concurrent mutation had already saved, plus any page
      // fetched in between.
      const prevFlags = new Map<number, { is_read: boolean; is_starred: boolean }>();
      for (const [, data] of prevEntries) {
        if (!data) continue;
        for (const page of data.pages)
          for (const e of page.entries)
            if (vars.ids.includes(e.id) && !prevFlags.has(e.id))
              prevFlags.set(e.id, { is_read: e.is_read, is_starred: e.is_starred });
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

      let countDelta: { perSub: Map<number, number>; total: number } | undefined;
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
        countDelta = { perSub, total };
      }
      return { prevFlags, prevDetails, countDelta };
    },
    onError: (_err, vars, ctx) => {
      // Undo exactly this mutation: the ids it patched, back to the values they had,
      // and the count delta it applied, negated. A snapshot restore would take a
      // concurrent mutation's saved change down with it.
      for (const id of vars.ids) {
        const prev = ctx?.prevFlags.get(id);
        if (prev) patchEntries(qc, new Set([id]), prev);
      }
      if (ctx?.countDelta) {
        const inverse = new Map<number, number>();
        for (const [sid, delta] of ctx.countDelta.perSub) inverse.set(sid, -delta);
        adjustCounts(qc, inverse, -ctx.countDelta.total);
      }
      for (const [id, d] of ctx?.prevDetails ?? []) qc.setQueryData(["entry", id], d);
      pushToast("Couldn't save your change — it was rolled back.", "error");
    },
    onSettled: (_data, _err, vars) => {
      // A star toggle can change membership of the starred stream. Skip it while
      // offline: the queries run networkMode "always" and the service worker answers
      // /streams from cache, so the refetch would serve the pre-mutation page and
      // visibly undo the optimistic patch while the real change sits in the outbox.
      if (vars.starred !== undefined && navigator.onLine)
        void qc.invalidateQueries({ queryKey: ["entries", "starred"] });
    },
  });
}

export function useMarkStreamRead(stream: StreamDescriptor) {
  const getToken = useTokenGetter();
  const qc = useQueryClient();
  const path = streamToPath(stream);
  return useMutation({
    // No argument → mark the whole stream read; a number bounds it to id <= that.
    mutationFn: async (maxEntryId?: number) => postMarkRead(await getToken(), path, maxEntryId),
    onMutate: async (maxEntryId) => {
      await qc.cancelQueries({ queryKey: ["entries"] });
      await qc.cancelQueries({ queryKey: queryKeys.counts });
      const prevEntries = qc.getQueriesData<EntriesData>({ queryKey: ["entries"] });
      const subs = qc.getQueryData<Subscription[]>(queryKeys.subscriptions);

      const affected = new Set<number>();
      const perSub = new Map<number, number>();
      let total = 0;
      // useStreamEntries keys entries as ["entries", path, q ?? null] — one cache
      // entry per search variant of a stream. Scan every variant of THIS stream (hence
      // the key[1] check) rather than guessing one exact key.
      //
      // Whoever edits this positional lookup next: the key has three elements, not
      // four. The comment here used to claim a `status` element that does not exist.
      for (const [key, data] of prevEntries) {
        if (key[1] !== path || !data) continue;
        for (const page of data.pages)
          for (const e of page.entries)
            if ((maxEntryId == null || e.id <= maxEntryId) && !e.is_read && !affected.has(e.id)) {
              affected.add(e.id);
              total -= 1;
              const sid = subIdForFeed(subs, e.feed_id);
              if (sid != null) perSub.set(sid, (perSub.get(sid) ?? 0) - 1);
            }
      }
      patchEntries(qc, affected, { is_read: true });
      adjustCounts(qc, perSub, total);
      return { affected, perSub, total };
    },
    onError: (_err, _vars, ctx) => {
      // Undo only the entries this call flipped, and only the counts it moved. All of
      // them were unread before, or they would not be in `affected`.
      if (ctx) {
        patchEntries(qc, ctx.affected, { is_read: false });
        const inverse = new Map<number, number>();
        for (const [sid, delta] of ctx.perSub) inverse.set(sid, -delta);
        adjustCounts(qc, inverse, -ctx.total);
      }
      pushToast("Couldn't mark all read — it was rolled back.", "error");
    },
    onSuccess: () => {
      // A clear "it's done" signal — the whole stream can be far larger than the
      // loaded window, so the optimistic change alone isn't obvious feedback.
      pushToast("Marked all as read.", "info");
    },
    // The whole stream got marked read — reconcile counts AND refetch the entries so
    // the list reflects the server (incl. entries below the loaded window), instead
    // of needing a manual refresh.
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.counts });
      void qc.invalidateQueries({ queryKey: ["entries"] });
    },
  });
}
