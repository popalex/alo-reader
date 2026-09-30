import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import { setAuthMode } from "../src/app/instance";
import * as toast from "../src/app/toast";
import { AddFeedContext } from "../src/features/layout/addFeed";
import { pendingPollDelay } from "../src/api/queries";
import { awaitingFirstFetch } from "../src/lib/streams";

const { importOpml, createSubscription } = vi.hoisted(() => ({
  importOpml: vi.fn(),
  createSubscription: vi.fn(),
}));
vi.mock("../src/api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("../src/api/endpoints")>("../src/api/endpoints");
  return { ...actual, importOpml, createSubscription };
});
vi.mock("../src/app/auth", () => ({ useTokenGetter: () => async () => null }));

import { Welcome } from "../src/features/welcome/Welcome";

function renderWelcome(openAddFeed = () => {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AddFeedContext.Provider value={{ openAddFeed }}>
        <Welcome />
      </AddFeedContext.Provider>
    </QueryClientProvider>,
  );
}

const opml = () => new File(["<opml/>"], "feeds.opml", { type: "text/xml" });

afterEach(() => {
  importOpml.mockReset();
  createSubscription.mockReset();
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

  it("reports an import where no feed could be added as an error, with the reason", async () => {
    const pushToast = vi.spyOn(toast, "pushToast");
    importOpml.mockResolvedValue({
      imported: 0,
      skipped: 0,
      failed: [{ url: "https://a.example/feed", reason: "quota exceeded" }],
    });
    const { container } = renderWelcome();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [opml()] } });
    await waitFor(() =>
      expect(pushToast).toHaveBeenCalledWith(
        "Couldn't import any feeds: 1 failed (quota exceeded).",
        "error",
      ),
    );
    pushToast.mockRestore();
  });

  it("says why an import failed", async () => {
    importOpml.mockRejectedValue(new ApiError(400, "invalid_request", "malformed OPML"));
    const { container } = renderWelcome();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [opml()] } });
    expect((await screen.findByRole("alert")).textContent).toContain("malformed OPML");
  });

  it("opens the app-wide add-feed dialog", () => {
    const openAddFeed = vi.fn();
    renderWelcome(openAddFeed);
    fireEvent.click(screen.getByRole("button", { name: "Add a feed" }));
    expect(openAddFeed).toHaveBeenCalledTimes(1);
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

describe("Welcome starter feeds", () => {
  it("subscribes to exactly the ticked feeds, with one button", async () => {
    createSubscription.mockImplementation(async (_token, input) => ({ id: 1, ...input }));
    renderWelcome();
    const button = screen.getByRole("button", { name: "Subscribe to ticked feeds" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    fireEvent.click(screen.getByLabelText(/NASA Image of the Day/));
    fireEvent.click(screen.getByLabelText(/Quanta Magazine/));
    fireEvent.click(screen.getByRole("button", { name: "Subscribe to 2 feeds" }));

    await waitFor(() => expect(createSubscription).toHaveBeenCalledTimes(2));
    expect(createSubscription.mock.calls.map((c) => c[1].feed_url)).toEqual([
      "https://www.nasa.gov/feeds/iotd-feed/",
      "https://www.quantamagazine.org/feed/",
    ]);
    expect(createSubscription.mock.calls[0][1]).toMatchObject({
      title: "NASA Image of the Day",
      folder_id: null,
    });
  });

  it("unticking takes a feed back out of the count", () => {
    renderWelcome();
    const xkcd = screen.getByLabelText(/xkcd/);
    fireEvent.click(xkcd);
    expect(screen.getByRole("button", { name: "Subscribe to 1 feed" })).toBeTruthy();
    fireEvent.click(xkcd);
    expect((screen.getByRole("button", { name: "Subscribe to ticked feeds" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps going when one feed fails, and says which reason", async () => {
    const pushToast = vi.spyOn(toast, "pushToast");
    createSubscription
      .mockRejectedValueOnce(new ApiError(422, "validation_error", "quota exceeded"))
      .mockImplementation(async (_token, input) => ({ id: 2, ...input }));
    renderWelcome();
    fireEvent.click(screen.getByLabelText(/BBC News/));
    fireEvent.click(screen.getByLabelText(/kottke\.org/));
    fireEvent.click(screen.getByRole("button", { name: "Subscribe to 2 feeds" }));
    await waitFor(() => expect(createSubscription).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(pushToast).toHaveBeenCalledWith(
        "Subscribed to 1 feed. 1 could not be added (quota exceeded).",
        "info",
      ),
    );
    pushToast.mockRestore();
  });

  it("reports an error, with the reason, when none could be added", async () => {
    const pushToast = vi.spyOn(toast, "pushToast");
    createSubscription.mockRejectedValue(new ApiError(429, "rate_limited", "too many requests"));
    renderWelcome();
    fireEvent.click(screen.getByLabelText(/Quanta Magazine/));
    fireEvent.click(screen.getByRole("button", { name: "Subscribe to 1 feed" }));
    await waitFor(() =>
      expect(pushToast).toHaveBeenCalledWith("Couldn't subscribe: too many requests.", "error"),
    );
    pushToast.mockRestore();
  });
});

describe("pendingPollDelay", () => {
  it("checks new feeds quickly at first, then slowly instead of giving up", () => {
    expect(pendingPollDelay(0)).toBe(2500);
    expect(pendingPollDelay(89_000)).toBe(2500);
    expect(pendingPollDelay(90_000)).toBe(30_000);
    expect(pendingPollDelay(9 * 60_000)).toBe(30_000);
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
