import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { updateFolder, updateSubscription } = vi.hoisted(() => ({
  updateFolder: vi.fn(),
  updateSubscription: vi.fn(),
}));
vi.mock("../src/api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("../src/api/endpoints")>("../src/api/endpoints");
  return { ...actual, updateFolder, updateSubscription };
});
vi.mock("../src/app/auth", () => ({ useTokenGetter: () => async () => null }));

import type { Folder, Subscription } from "../src/api/endpoints";
import { useUpdateFolder, useUpdateSubscription } from "../src/api/feedMutations";
import { queryKeys } from "../src/api/queries";

const folders: Folder[] = [{ id: 1, name: "Tech", position: 0 }];
const subs: Subscription[] = [
  {
    id: 5,
    feed_id: 50,
    title: "The Verge",
    feed_url: "https://verge.example/feed",
    site_url: null,
    folder_id: 1,
    icon_url: null,
    last_error: null,
    last_fetched_at: null,
  },
];

/** A client pre-seeded with the sidebar's two lists, so a mutation has something
 *  to patch without a network round trip. */
function seeded() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(queryKeys.folders, folders);
  qc.setQueryData(queryKeys.subscriptions, subs);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return { qc, wrapper };
}

const folderNames = (qc: QueryClient) =>
  qc.getQueryData<Folder[]>(queryKeys.folders)?.map((f) => f.name);
const subTitles = (qc: QueryClient) =>
  qc.getQueryData<Subscription[]>(queryKeys.subscriptions)?.map((s) => s.title);

afterEach(() => vi.clearAllMocks());

describe("renames patch the cache before the request settles", () => {
  it("shows a renamed category while the PATCH is still in flight", async () => {
    const { qc, wrapper } = seeded();
    // Never resolves: the sidebar must not wait on it. This is the nightly flake —
    // the inline editor closes on Enter, so a slow PATCH left the old name on screen.
    updateFolder.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useUpdateFolder(), { wrapper });

    act(() => result.current.mutate({ id: 1, name: "Reading" }));

    await waitFor(() => expect(folderNames(qc)).toEqual(["Reading"]));
  });

  it("puts the old category name back when the rename fails", async () => {
    const { qc, wrapper } = seeded();
    updateFolder.mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useUpdateFolder(), { wrapper });

    act(() => result.current.mutate({ id: 1, name: "Reading" }));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(folderNames(qc)).toEqual(["Tech"]);
  });

  it("shows a renamed feed while the PATCH is still in flight", async () => {
    const { qc, wrapper } = seeded();
    updateSubscription.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useUpdateSubscription(), { wrapper });

    act(() => result.current.mutate({ id: 5, title_override: "Verge Renamed" }));

    await waitFor(() => expect(subTitles(qc)).toEqual(["Verge Renamed"]));
  });

  it("leaves a cleared title override to the refetch", async () => {
    const { qc, wrapper } = seeded();
    updateSubscription.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useUpdateSubscription(), { wrapper });

    // "" clears the override and the feed falls back to its own title, which only
    // the server knows — so there is nothing to patch optimistically.
    act(() => result.current.mutate({ id: 5, title_override: "" }));

    await waitFor(() => expect(updateSubscription).toHaveBeenCalled());
    expect(subTitles(qc)).toEqual(["The Verge"]);
  });
});
