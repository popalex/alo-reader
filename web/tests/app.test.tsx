import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApiConfig } from "../src/api/client";
import type { Counts, Folder, Subscription } from "../src/api/endpoints";

// Hoisted so the vi.mock factories below can close over these fns safely.
const { getConfig } = vi.hoisted(() => ({ getConfig: vi.fn() }));
const { getFolders, getSubscriptions, getCounts } = vi.hoisted(() => ({
  getFolders: vi.fn(),
  getSubscriptions: vi.fn(),
  getCounts: vi.fn(),
}));

// Keep the real transport (ApiError etc.) but stub the network calls.
vi.mock("../src/api/client", async () => {
  const actual = await vi.importActual<typeof import("../src/api/client")>("../src/api/client");
  return { ...actual, getConfig };
});
vi.mock("../src/api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("../src/api/endpoints")>("../src/api/endpoints");
  return { ...actual, getFolders, getSubscriptions, getCounts };
});

// Stub the Clerk chunk: proves the branch loads it without pulling real Clerk
// (which needs a live publishable key + network) into the test.
vi.mock("../src/app/ClerkApp", () => ({
  default: ({ publishableKey }: { publishableKey: string }) => (
    <div data-testid="clerk-app">clerk:{publishableKey}</div>
  ),
}));

import { App } from "../src/App";

const folders: Folder[] = [{ id: 1, name: "Tech", position: 0 }];
const subscriptions: Subscription[] = [
  {
    id: 11,
    feed_id: 101,
    title: "Hacker News",
    site_url: "https://news.ycombinator.com",
    folder_id: 1,
    icon_url: null,
    last_error: null,
    last_fetched_at: null,
  },
  {
    id: 12,
    feed_id: 102,
    title: "Reuters",
    site_url: null,
    folder_id: null, // uncategorised
    icon_url: null,
    last_error: "connection refused",
    last_fetched_at: null,
  },
];
const counts: Counts = {
  total_unread: 8,
  subscriptions: [
    { id: 11, unread: 5 },
    { id: 12, unread: 3 },
  ],
};

afterEach(() => {
  vi.clearAllMocks();
});

describe("App boot", () => {
  it("none mode renders the three-pane app with live sidebar data", async () => {
    getConfig.mockResolvedValue({ auth_mode: "none" } satisfies ApiConfig);
    getFolders.mockResolvedValue(folders);
    getSubscriptions.mockResolvedValue(subscriptions);
    getCounts.mockResolvedValue(counts);

    render(<App />);

    // Feed rows from /subscriptions, grouped and ungrouped.
    await waitFor(() => expect(screen.getByText("Hacker News")).toBeDefined());
    expect(screen.getByText("Reuters")).toBeDefined();
    // Folder group + fixed views (scoped to the sidebar nav: "All items" also
    // appears as the active stream's list-header title).
    expect(screen.getByText("Tech")).toBeDefined();
    const views = screen.getByRole("navigation", { name: "Views" });
    expect(within(views).getByText("All items")).toBeDefined();
    expect(within(views).getByText("Starred")).toBeDefined();
    // Total-unread badge on All items, per-feed badge on the uncategorised feed.
    expect(screen.getByText("8")).toBeDefined();
    expect(screen.getByText("3")).toBeDefined();
    // Error dot for the feed with last_error.
    expect(screen.getByTitle("This feed failed to update")).toBeDefined();
    // Never loaded Clerk in none mode.
    expect(screen.queryByTestId("clerk-app")).toBeNull();
  });

  it("clerk mode lazy-loads the Clerk shell and defers data until sign-in", async () => {
    getConfig.mockResolvedValue({
      auth_mode: "clerk",
      clerk_publishable_key: "pk_test_boot",
    } satisfies ApiConfig);

    render(<App />);

    await waitFor(() => expect(screen.getByTestId("clerk-app")).toBeDefined());
    expect(screen.getByTestId("clerk-app").textContent).toContain("pk_test_boot");
    // The app (and its data calls) mounts only after sign-in, inside the shell.
    expect(getSubscriptions).not.toHaveBeenCalled();
  });

  it("surfaces a boot error when /config is unreachable", async () => {
    getConfig.mockRejectedValue(new Error("network down"));

    render(<App />);

    await waitFor(() => expect(screen.getByRole("alert")).toBeDefined());
    expect(screen.getByRole("alert").textContent).toContain("Could not start");
  });

  it("errors clearly when clerk mode arrives without a publishable key", async () => {
    getConfig.mockResolvedValue({ auth_mode: "clerk" } satisfies ApiConfig);

    render(<App />);

    await waitFor(() => expect(screen.getByRole("alert")).toBeDefined());
    expect(screen.getByRole("alert").textContent).toContain("no publishable key");
    expect(screen.queryByTestId("clerk-app")).toBeNull();
  });
});
