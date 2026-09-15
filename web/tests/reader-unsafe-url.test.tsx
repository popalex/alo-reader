// The wiring half of the javascript:-URL guard: ReaderPane must not put a stored
// hostile URL into an href, and the keyboard "open original" must not hand one to
// window.open (which runs it in a document inheriting this origin).

import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const { getEntry } = vi.hoisted(() => ({ getEntry: vi.fn() }));
vi.mock("../src/api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("../src/api/endpoints")>("../src/api/endpoints");
  return { ...actual, getEntry };
});
vi.mock("../src/app/auth", () => ({ useTokenGetter: () => async () => null }));
vi.mock("../src/app/offline/useOffline", () => ({ useOnline: () => true }));
vi.mock("../src/features/stream/selection", async () => {
  const actual = await vi.importActual<typeof import("../src/features/stream/selection")>(
    "../src/features/stream/selection",
  );
  return {
    ...actual,
    useSelection: () => ({
      cursorId: 7,
      openId: 7,
      setCursor: () => {},
      open: () => {},
      close: () => {},
      clear: () => {},
    }),
  };
});

import { ReaderPane } from "../src/features/stream/ReaderPane";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

afterEach(() => vi.clearAllMocks());

describe("ReaderPane with a hostile stored URL", () => {
  it("renders no link for a javascript: URL", async () => {
    getEntry.mockResolvedValue({
      id: 7,
      feed_id: 1,
      feed_title: "Feed",
      title: "Post",
      author: null,
      url: "javascript:alert(document.cookie)",
      published_at: null,
      created_at: "2026-01-01T00:00:00Z",
      content_html: "<p>body</p>",
      is_read: false,
      is_starred: false,
    });

    render(<ReaderPane />, { wrapper });

    await waitFor(() => expect(screen.getByText("Post")).toBeTruthy());
    expect(screen.queryByText("Open original")).toBeNull();
    for (const a of document.querySelectorAll("a")) {
      expect(a.getAttribute("href") ?? "").not.toContain("javascript:");
    }
  });

  it("still links an ordinary https URL", async () => {
    getEntry.mockResolvedValue({
      id: 7,
      feed_id: 1,
      feed_title: "Feed",
      title: "Post",
      author: null,
      url: "https://example.com/post",
      published_at: null,
      created_at: "2026-01-01T00:00:00Z",
      content_html: "<p>body</p>",
      is_read: false,
      is_starred: false,
    });

    render(<ReaderPane />, { wrapper });

    await waitFor(() => expect(screen.getByText("Open original")).toBeTruthy());
    expect(screen.getByText("Open original").closest("a")?.getAttribute("href")).toBe(
      "https://example.com/post",
    );
  });
});
