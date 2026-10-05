import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import * as toast from "../src/app/toast";
import { localDateStamp } from "../src/lib/download";

const { exportOpml } = vi.hoisted(() => ({ exportOpml: vi.fn() }));
vi.mock("../src/api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("../src/api/endpoints")>("../src/api/endpoints");
  return { ...actual, exportOpml };
});
// Clerk mode: the export has to carry the token, which is why it isn't a plain link.
vi.mock("../src/app/auth", () => ({ useTokenGetter: () => async () => "tok" }));

import { ExportFeedsButton } from "../src/features/sidebar/ExportFeedsButton";

function renderButton() {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ExportFeedsButton />
    </QueryClientProvider>,
  );
}

// jsdom has no object URLs and doesn't download on click; record what would be saved.
const saved: { href: string; download: string }[] = [];
beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:export");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    saved.push({ href: this.href, download: this.download });
  });
});
afterEach(() => {
  saved.length = 0;
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("ExportFeedsButton", () => {
  it("fetches the OPML with the token and saves it under a dated name", async () => {
    const blob = new Blob(["<opml/>"], { type: "text/x-opml" });
    exportOpml.mockResolvedValue(blob);
    renderButton();

    fireEvent.click(screen.getByRole("button", { name: "Export feeds (OPML)" }));

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(exportOpml).toHaveBeenCalledWith("tok");
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
    expect(saved[0]).toEqual({ href: "blob:export", download: `alo-reader-${localDateStamp()}.opml` });
    // The anchor was only there for the click.
    expect(document.querySelector("a[download]")).toBeNull();
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:export"));
  });

  it.each([
    { online: true, message: "Couldn't export your feeds — try again." },
    { online: false, message: "You're offline. Export your feeds when you're back online." },
  ])("says so when the export fails (online: $online), and saves nothing", async ({ online, message }) => {
    // Restored by vi.restoreAllMocks in afterEach.
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(online);
    const pushToast = vi.spyOn(toast, "pushToast");
    exportOpml.mockRejectedValue(online ? new ApiError(500, "internal", "boom") : new TypeError("Failed to fetch"));
    renderButton();

    fireEvent.click(screen.getByRole("button", { name: "Export feeds (OPML)" }));

    await waitFor(() => expect(pushToast).toHaveBeenCalledWith(message, "error"));
    expect(saved).toHaveLength(0);
    const button = screen.getByRole<HTMLButtonElement>("button", { name: "Export feeds (OPML)" });
    await waitFor(() => expect(button.disabled).toBe(false));
  });
});

describe("localDateStamp", () => {
  it("uses the local date, zero-padded", () => {
    expect(localDateStamp(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
  });
});
