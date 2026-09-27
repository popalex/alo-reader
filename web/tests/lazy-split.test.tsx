// The dialogs and DOMPurify moved out of the startup bundle. What must not change:
// a dialog mounts on its first open and then stays mounted (close animations and
// Radix focus return depend on it), and the reader never renders unsanitized HTML.

import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as toast from "../src/app/toast";
import { lazyDialog } from "../src/components/lazyDialog";
import { loadSanitizer, useSanitizer } from "../src/lib/sanitize";

function Probe({ open }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return <div data-testid="probe" data-open={String(open)} />;
}

describe("lazyDialog", () => {
  it("loads nothing and renders nothing until first opened", async () => {
    const load = vi.fn(() => Promise.resolve(Probe));
    const Dialog = lazyDialog(load);
    render(<Dialog open={false} onOpenChange={() => {}} />);
    expect(screen.queryByTestId("probe")).toBeNull();
    expect(load).not.toHaveBeenCalled();
  });

  it("stays mounted after it closes, so exit animations and focus return still run", async () => {
    const Dialog = lazyDialog(() => Promise.resolve(Probe));
    const { rerender } = render(<Dialog open onOpenChange={() => {}} />);
    expect((await screen.findByTestId("probe")).dataset.open).toBe("true");

    rerender(<Dialog open={false} onOpenChange={() => {}} />);
    expect(screen.getByTestId("probe").dataset.open).toBe("false");
  });
  it("survives a chunk that fails to load: toast, dialog closed, app still rendered", async () => {
    // A deploy while the app is open: the old hashed chunk is gone and import() 404s.
    // Real browsers then need a reload (a failed import is cached for the page); the
    // second open below only shows the wrapper itself doesn't stay stuck.
    const toastSpy = vi.spyOn(toast, "pushToast");
    const load = vi
      .fn<() => Promise<typeof Probe>>()
      .mockRejectedValueOnce(new TypeError("Failed to fetch dynamically imported module"))
      .mockResolvedValue(Probe);
    const Dialog = lazyDialog(load);
    const onOpenChange = vi.fn();

    const { rerender } = render(<Dialog open onOpenChange={onOpenChange} />);
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(toastSpy).toHaveBeenCalledOnce();
    expect(screen.queryByTestId("probe")).toBeNull();

    rerender(<Dialog open={false} onOpenChange={onOpenChange} />);
    rerender(<Dialog open onOpenChange={onOpenChange} />);
    expect((await screen.findByTestId("probe")).dataset.open).toBe("true");
    expect(load).toHaveBeenCalledTimes(2);
    toastSpy.mockRestore();
  });
});

describe("useSanitizer", () => {
  it("does not fetch DOMPurify until there is content to sanitize", async () => {
    const { result, rerender } = renderHook(({ needed }) => useSanitizer(needed), {
      initialProps: { needed: false },
    });
    expect(result.current.sanitize).toBeUndefined();
    rerender({ needed: true });
    await waitFor(() => expect(result.current.sanitize).toBeDefined());
    expect(result.current.failed).toBe(false);
  });
});

describe("loadSanitizer", () => {
  it("strips scripts and event handlers once loaded", async () => {
    const sanitize = await act(() => loadSanitizer());
    const out = sanitize('<p onclick="x()">hi</p><script>alert(1)</script><img src=x onerror=alert(1)>');
    expect(out).not.toMatch(/script|onclick|onerror/);
    expect(out).toContain("<p>hi</p>");
  });
});
