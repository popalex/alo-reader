import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApiConfig, Me } from "../src/api/client";

// Hoisted so the vi.mock factory below can close over these fns safely.
const { getConfig, getMe } = vi.hoisted(() => ({
  getConfig: vi.fn(),
  getMe: vi.fn(),
}));

// Keep the real transport (ApiError etc.) but stub the two network calls.
vi.mock("../src/api/client", async () => {
  const actual = await vi.importActual<typeof import("../src/api/client")>("../src/api/client");
  return { ...actual, getConfig, getMe };
});

// Stub the Clerk chunk: proves the branch loads it without pulling real Clerk
// (which needs a live publishable key + network) into the test.
vi.mock("../src/app/ClerkApp", () => ({
  default: ({ publishableKey }: { publishableKey: string }) => (
    <div data-testid="clerk-app">clerk:{publishableKey}</div>
  ),
}));

import { App } from "../src/App";

const me: Me = {
  id: 1,
  email: "reader@example.com",
  quotas: { subscriptions: 100 },
  counts_summary: { total_unread: 3 },
};

afterEach(() => {
  vi.clearAllMocks();
});

describe("App boot", () => {
  it("none mode renders the app directly and never loads Clerk", async () => {
    getConfig.mockResolvedValue({ auth_mode: "none" } satisfies ApiConfig);
    getMe.mockResolvedValue(me);

    render(<App />);

    await waitFor(() => expect(screen.getByText(/Signed in as/)).toBeDefined());
    expect(screen.getByText(/reader@example.com/)).toBeDefined();
    expect(screen.queryByTestId("clerk-app")).toBeNull();
    // Bare request: none mode carries no token.
    expect(getMe).toHaveBeenCalledWith(null);
  });

  it("clerk mode lazy-loads the Clerk shell with the server's publishable key", async () => {
    getConfig.mockResolvedValue({
      auth_mode: "clerk",
      clerk_publishable_key: "pk_test_boot",
    } satisfies ApiConfig);

    render(<App />);

    await waitFor(() => expect(screen.getByTestId("clerk-app")).toBeDefined());
    expect(screen.getByTestId("clerk-app").textContent).toContain("pk_test_boot");
    // Home (and its /me call) mounts only after sign-in, inside the Clerk shell.
    expect(getMe).not.toHaveBeenCalled();
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
