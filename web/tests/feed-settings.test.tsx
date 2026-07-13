import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { updateSubscription, createFolder } = vi.hoisted(() => ({
  updateSubscription: vi.fn(),
  createFolder: vi.fn(),
}));
vi.mock("../src/api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("../src/api/endpoints")>("../src/api/endpoints");
  return { ...actual, updateSubscription, createFolder };
});
vi.mock("../src/app/auth", () => ({ useTokenGetter: () => async () => null }));

import type { Folder, Subscription } from "../src/api/endpoints";
import { FeedSettingsDialog } from "../src/features/subscribe/FeedSettingsDialog";

const sub: Subscription = {
  id: 5,
  feed_id: 50,
  title: "Old Title",
  feed_url: "https://ex.example/feed",
  site_url: null,
  folder_id: null,
  icon_url: null,
  last_error: null,
  last_fetched_at: null,
};
const folders: Folder[] = [{ id: 3, name: "Tech", position: 0 }];

function renderDialog(onDelete = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <FeedSettingsDialog
        sub={sub}
        open
        onOpenChange={() => {}}
        folders={folders}
        onDelete={onDelete}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.clearAllMocks());

describe("FeedSettingsDialog", () => {
  it("renames the feed and moves it to a category", async () => {
    updateSubscription.mockResolvedValue(sub);
    renderDialog();

    fireEvent.change(screen.getByLabelText(/^title$/i), { target: { value: "New Title" } });
    fireEvent.change(screen.getByLabelText(/^category$/i), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(updateSubscription).toHaveBeenCalledWith(null, 5, {
        title_override: "New Title",
        folder_id: 3,
      }),
    );
  });

  it("saves nothing when unchanged", async () => {
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    // No field changed → no PATCH.
    await new Promise((r) => setTimeout(r, 0));
    expect(updateSubscription).not.toHaveBeenCalled();
  });

  it("delete routes to onDelete", () => {
    const onDelete = vi.fn();
    renderDialog(onDelete);
    fireEvent.click(screen.getByRole("button", { name: /delete feed/i }));
    expect(onDelete).toHaveBeenCalledWith(sub);
  });
});
