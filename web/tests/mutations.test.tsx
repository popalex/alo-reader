// Unit tests for the optimistic-update core (src/api/mutations.ts): the count
// math, the multi-variant cache patch, and rollback. These are pure, fiddly, and
// the thing users notice when wrong (bad unread badges), so they're pinned here
// rather than only exercised end-to-end.

import {
  QueryClient,
  QueryClientProvider,
  type InfiniteData,
} from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { ApiError } from "../src/api/client";

const { postEntryState, postMarkRead } = vi.hoisted(() => ({
  postEntryState: vi.fn(),
  postMarkRead: vi.fn(),
}));
vi.mock("../src/api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("../src/api/endpoints")>("../src/api/endpoints");
  return { ...actual, postEntryState, postMarkRead };
});
vi.mock("../src/app/auth", () => ({ useTokenGetter: () => async () => null }));
const { pushToast } = vi.hoisted(() => ({ pushToast: vi.fn() }));
vi.mock("../src/app/toast", () => ({ pushToast }));

import { useMarkStreamRead, useSetEntryState } from "../src/api/mutations";
import { queryKeys } from "../src/api/queries";
import type { Counts, EntryListItem, StreamPage, Subscription } from "../src/api/endpoints";

type EntriesData = InfiniteData<StreamPage>;

function entry(over: Partial<EntryListItem> & { id: number; feed_id: number }): EntryListItem {
  return {
    author: null,
    created_at: "2020-01-01T00:00:00Z",
    feed_title: "Feed",
    is_read: false,
    is_starred: false,
    published_at: null,
    summary: "",
    title: "t",
    url: null,
    ...over,
  };
}

function page(entries: EntryListItem[]): EntriesData {
  return { pages: [{ entries, next_cursor: null }], pageParams: [null] };
}

// subIdForFeed only reads id + feed_id, so a minimal cast is enough.
const subs = [
  { id: 10, feed_id: 100 },
  { id: 11, feed_id: 101 },
] as unknown as Subscription[];

function seededClient(): QueryClient {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["entries", "all", null], page([entry({ id: 1, feed_id: 100 }), entry({ id: 2, feed_id: 101 })]));
  qc.setQueryData<Counts>(queryKeys.counts, {
    total_unread: 5,
    subscriptions: [
      { id: 10, unread: 3 },
      { id: 11, unread: 2 },
    ],
  });
  qc.setQueryData(queryKeys.subscriptions, subs);
  return qc;
}

const wrapper = (qc: QueryClient) =>
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };

afterEach(() => vi.clearAllMocks());

describe("useSetEntryState", () => {
  it("optimistically flips read and keeps per-sub + total counts exact", async () => {
    postEntryState.mockResolvedValue({ updated: 1 });
    const qc = seededClient();
    const { result } = renderHook(() => useSetEntryState(), { wrapper: wrapper(qc) });

    await act(async () => {
      result.current.mutate({ ids: [1], read: true });
    });
    await waitFor(() => expect(postEntryState).toHaveBeenCalled());

    const entries = qc.getQueryData<EntriesData>(["entries", "all", null])!;
    expect(entries.pages[0].entries[0].is_read).toBe(true);
    expect(entries.pages[0].entries[1].is_read).toBe(false);

    const counts = qc.getQueryData<Counts>(queryKeys.counts)!;
    expect(counts.total_unread).toBe(4);
    expect(counts.subscriptions.find((s) => s.id === 10)!.unread).toBe(2);
    expect(counts.subscriptions.find((s) => s.id === 11)!.unread).toBe(2);
  });

  it("does not push a count below zero", async () => {
    postEntryState.mockResolvedValue({ updated: 1 });
    const qc = seededClient();
    qc.setQueryData<Counts>(queryKeys.counts, {
      total_unread: 0,
      subscriptions: [{ id: 10, unread: 0 }],
    });
    const { result } = renderHook(() => useSetEntryState(), { wrapper: wrapper(qc) });

    // Marking an already-unread entry read when the count is already 0 must clamp.
    await act(async () => {
      result.current.mutate({ ids: [1], read: true });
    });
    await waitFor(() => expect(postEntryState).toHaveBeenCalled());

    const counts = qc.getQueryData<Counts>(queryKeys.counts)!;
    expect(counts.total_unread).toBe(0);
    expect(counts.subscriptions[0].unread).toBe(0);
  });

  it("rolls back the optimistic change and toasts on a server error", async () => {
    postEntryState.mockRejectedValue(new ApiError(500, "internal", "boom"));
    const qc = seededClient();
    const { result } = renderHook(() => useSetEntryState(), { wrapper: wrapper(qc) });

    await act(async () => {
      result.current.mutate({ ids: [1], read: true });
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const entries = qc.getQueryData<EntriesData>(["entries", "all", null])!;
    expect(entries.pages[0].entries[0].is_read).toBe(false);
    expect(qc.getQueryData<Counts>(queryKeys.counts)!.total_unread).toBe(5);
    expect(pushToast).toHaveBeenCalled();
  });
});

describe("useMarkStreamRead", () => {
  it("patches every cached variant of the same stream", async () => {
    postMarkRead.mockResolvedValue({ updated: 2 });
    const qc = seededClient();
    // A second variant of the same "all" stream (e.g. an active search).
    qc.setQueryData(["entries", "all", "react"], page([entry({ id: 1, feed_id: 100 })]));

    const { result } = renderHook(() => useMarkStreamRead({ kind: "all" }), { wrapper: wrapper(qc) });
    await act(async () => {
      result.current.mutate(undefined);
    });
    await waitFor(() => expect(postMarkRead).toHaveBeenCalled());

    const base = qc.getQueryData<EntriesData>(["entries", "all", null])!;
    const search = qc.getQueryData<EntriesData>(["entries", "all", "react"])!;
    expect(base.pages[0].entries.every((e) => e.is_read)).toBe(true);
    expect(search.pages[0].entries.every((e) => e.is_read)).toBe(true);
  });
});
