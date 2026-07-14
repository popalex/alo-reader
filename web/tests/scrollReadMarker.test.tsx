// Unit tests for useScrollReadMarker (mark-read-on-scroll-past): the firstVisible
// computation from the virtualizer range, and the search-toggle watermark reset.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const { postEntryState } = vi.hoisted(() => ({ postEntryState: vi.fn() }));
vi.mock("../src/api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("../src/api/endpoints")>("../src/api/endpoints");
  return { ...actual, postEntryState };
});
vi.mock("../src/app/auth", () => ({ useTokenGetter: () => async () => null }));

import { useScrollReadMarker } from "../src/features/stream/useScrollReadMarker";
import type { EntryListItem } from "../src/api/endpoints";

function entry(id: number): EntryListItem {
  return {
    author: null,
    created_at: "2020-01-01T00:00:00Z",
    feed_id: 1,
    feed_title: "Feed",
    id,
    is_read: false,
    is_starred: false,
    published_at: null,
    summary: "",
    title: "t",
    url: null,
  };
}

// Four 50px rows stacked; getVirtualItems returns their measured range.
const items = [
  { index: 0, start: 0, size: 50 },
  { index: 1, start: 50, size: 50 },
  { index: 2, start: 100, size: 50 },
  { index: 3, start: 150, size: 50 },
];
const virtualizer = { getVirtualItems: () => items };

const wrapper = (qc: QueryClient) =>
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };

afterEach(() => vi.clearAllMocks());

describe("useScrollReadMarker", () => {
  it("marks rows scrolled fully above the fold, in one batched request", async () => {
    postEntryState.mockResolvedValue({ updated: 2 });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const el = document.createElement("div");
    const entries = [entry(1), entry(2), entry(3), entry(4)];

    renderHook(() => useScrollReadMarker(el, virtualizer, entries, false), { wrapper: wrapper(qc) });

    // Scroll so rows 0 and 1 (bottoms at 50 and 100) are above the top edge (120).
    el.scrollTop = 120;
    el.dispatchEvent(new Event("scroll"));

    await waitFor(() => expect(postEntryState).toHaveBeenCalledTimes(1), { timeout: 1500 });
    expect(postEntryState.mock.calls[0][1]).toMatchObject({ ids: [1, 2], read: true });
  });

  it("resets the watermark when the search state toggles", async () => {
    postEntryState.mockResolvedValue({ updated: 2 });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const el = document.createElement("div");
    const entries = [entry(1), entry(2), entry(3), entry(4)];

    const { rerender } = renderHook(
      ({ resetKey }: { resetKey: boolean }) => useScrollReadMarker(el, virtualizer, entries, resetKey),
      { wrapper: wrapper(qc), initialProps: { resetKey: false } },
    );

    el.scrollTop = 120;
    el.dispatchEvent(new Event("scroll"));
    await waitFor(() => expect(postEntryState).toHaveBeenCalledTimes(1), { timeout: 1500 });

    // Without a reset, scrolling to the same place again marks nothing (watermark).
    el.dispatchEvent(new Event("scroll"));
    await new Promise((r) => setTimeout(r, 800));
    expect(postEntryState).toHaveBeenCalledTimes(1);

    // Toggling the search state resets the watermark, so the same rows re-mark.
    rerender({ resetKey: true });
    el.dispatchEvent(new Event("scroll"));
    await waitFor(() => expect(postEntryState).toHaveBeenCalledTimes(2), { timeout: 1500 });
  });
});
