import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import { setAuthMode } from "../src/app/instance";
import { awaitingFirstFetch } from "../src/lib/streams";

const { importOpml } = vi.hoisted(() => ({ importOpml: vi.fn() }));
vi.mock("../src/api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("../src/api/endpoints")>("../src/api/endpoints");
  return { ...actual, importOpml };
});
vi.mock("../src/app/auth", () => ({ useTokenGetter: () => async () => null }));

import { Welcome } from "../src/features/welcome/Welcome";

function renderWelcome(onAddFeed = () => {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Welcome onAddFeed={onAddFeed} />
    </QueryClientProvider>,
  );
}

const opml = () => new File(["<opml/>"], "feeds.opml", { type: "text/xml" });

afterEach(() => {
  importOpml.mockReset();
  setAuthMode("none");
});

describe("Welcome", () => {
  it("imports the chosen OPML file straight from the welcome screen", async () => {
    importOpml.mockResolvedValue({ imported: 3, skipped: 0, failed: [] });
    const { container } = renderWelcome();
    expect(screen.getByRole("heading", { name: "Welcome to alo reader", level: 1 })).toBeTruthy();

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = opml();
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(importOpml).toHaveBeenCalledTimes(1));
    expect(importOpml.mock.calls[0][1]).toBe(file);
  });

  it("says why an import failed", async () => {
    importOpml.mockRejectedValue(new ApiError(400, "invalid_request", "malformed OPML"));
    const { container } = renderWelcome();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [opml()] } });
    expect((await screen.findByRole("alert")).textContent).toContain("malformed OPML");
  });

  it("opens the add-feed dialog through its callback", () => {
    const onAddFeed = vi.fn();
    renderWelcome(onAddFeed);
    fireEvent.click(screen.getByRole("button", { name: "Add a feed" }));
    expect(onAddFeed).toHaveBeenCalledTimes(1);
  });

  it("links the export guides only where the website serves them", () => {
    const { unmount } = renderWelcome();
    expect(screen.queryByRole("link", { name: "from Feedly" })).toBeNull();
    unmount();

    setAuthMode("clerk");
    renderWelcome();
    expect(screen.getByRole("link", { name: "from Feedly" }).getAttribute("href")).toBe("/from/feedly");
    expect(screen.getByRole("link", { name: "from Inoreader" }).getAttribute("href")).toBe("/from/inoreader");
  });
});

describe("awaitingFirstFetch", () => {
  const sub = (feed_id: number, folder_id: number | null, fetched: boolean, error = false) => ({
    feed_id,
    folder_id,
    last_fetched_at: fetched ? "2026-09-30T08:00:00Z" : null,
    last_error: error ? "HTTP 404" : null,
  });

  it("waits while any feed in the stream has never been fetched", () => {
    const subs = [sub(1, 10, true), sub(2, 20, false)];
    expect(awaitingFirstFetch({ kind: "all" }, subs)).toBe(true);
    expect(awaitingFirstFetch({ kind: "folder", id: 20 }, subs)).toBe(true);
    expect(awaitingFirstFetch({ kind: "folder", id: 10 }, subs)).toBe(false);
    expect(awaitingFirstFetch({ kind: "feed", id: 2 }, subs)).toBe(true);
    expect(awaitingFirstFetch({ kind: "feed", id: 1 }, subs)).toBe(false);
  });

  it("stops waiting for a feed that failed, and never waits on Starred", () => {
    expect(awaitingFirstFetch({ kind: "all" }, [sub(1, null, false, true)])).toBe(false);
    expect(awaitingFirstFetch({ kind: "starred" }, [sub(1, null, false)])).toBe(false);
  });
});
