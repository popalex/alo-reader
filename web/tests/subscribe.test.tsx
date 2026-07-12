import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";

// Stub the network endpoints; keep everything else (types, apiFetch) real.
const { discoverFeeds, createSubscription, importOpml } = vi.hoisted(() => ({
  discoverFeeds: vi.fn(),
  createSubscription: vi.fn(),
  importOpml: vi.fn(),
}));
vi.mock("../src/api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("../src/api/endpoints")>("../src/api/endpoints");
  return { ...actual, discoverFeeds, createSubscription, importOpml };
});
// AUTH_MODE=none: the token getter yields null, no Clerk needed.
vi.mock("../src/app/auth", () => ({ useTokenGetter: () => async () => null }));

import { AddSubscriptionDialog } from "../src/features/subscribe/AddSubscriptionDialog";

const aSub = {
  id: 1,
  feed_id: 1,
  title: "Example",
  site_url: null,
  folder_id: null,
  icon_url: null,
  last_error: null,
  last_fetched_at: null,
};

function renderDialog(onOpenChange = () => {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AddSubscriptionDialog open onOpenChange={onOpenChange} folders={[]} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.clearAllMocks());

describe("AddSubscriptionDialog", () => {
  it("discovers feeds from a URL then subscribes to the chosen candidate", async () => {
    discoverFeeds.mockResolvedValue([{ feed_url: "https://ex.com/feed.xml", title: "Example" }]);
    createSubscription.mockResolvedValue(aSub);
    const onOpenChange = vi.fn();
    renderDialog(onOpenChange);

    fireEvent.change(screen.getByLabelText(/feed or site url/i), { target: { value: "ex.com" } });
    fireEvent.click(screen.getByRole("button", { name: /find/i }));

    const add = await screen.findByRole("button", { name: /add/i });
    expect(discoverFeeds).toHaveBeenCalledWith(null, "ex.com");

    fireEvent.click(add);
    await waitFor(() =>
      expect(createSubscription).toHaveBeenCalledWith(null, {
        feed_url: "https://ex.com/feed.xml",
        folder_id: null,
      }),
    );
    // Subscribing closes the dialog.
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("surfaces a server error (already subscribed) without closing", async () => {
    discoverFeeds.mockResolvedValue([{ feed_url: "https://ex.com/feed.xml", title: "Example" }]);
    createSubscription.mockRejectedValue(
      new ApiError(409, "duplicate", "You're already subscribed to that feed."),
    );
    renderDialog();

    fireEvent.change(screen.getByLabelText(/feed or site url/i), { target: { value: "ex.com" } });
    fireEvent.click(screen.getByRole("button", { name: /find/i }));
    fireEvent.click(await screen.findByRole("button", { name: /add/i }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/already subscribed/i);
  });

  it("imports an OPML file and shows the report", async () => {
    importOpml.mockResolvedValue({
      imported: 3,
      skipped: 1,
      failed: [{ url: "http://bad.example", reason: "not a feed" }],
    });
    renderDialog();

    const file = new File(["<opml/>"], "feeds.opml", { type: "text/xml" });
    fireEvent.change(screen.getByLabelText(/choose opml file/i), { target: { files: [file] } });

    await waitFor(() => expect(importOpml).toHaveBeenCalledWith(null, file));
    const summary = await screen.findByText(/imported 3/i);
    expect(summary.textContent).toMatch(/skipped 1/i);
    await screen.findByText(/not a feed/i); // failure row rendered
  });

  it("shows a message when no feeds are found", async () => {
    discoverFeeds.mockResolvedValue([]);
    renderDialog();

    fireEvent.change(screen.getByLabelText(/feed or site url/i), { target: { value: "nope.example" } });
    fireEvent.click(screen.getByRole("button", { name: /find/i }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/no feeds found/i);
  });
});
