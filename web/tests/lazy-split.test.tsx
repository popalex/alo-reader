// The dialogs and DOMPurify moved out of the startup bundle. What must not change:
// a dialog mounts on its first open and then stays mounted (close animations and
// Radix focus return depend on it), and the reader never renders unsanitized HTML.

import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { lazyDialog } from "../src/components/lazyDialog";
import { loadSanitizer } from "../src/lib/sanitize";

function Probe({ open }: { open: boolean }) {
  return <div data-testid="probe" data-open={String(open)} />;
}

describe("lazyDialog", () => {
  it("loads nothing and renders nothing until first opened", async () => {
    const load = vi.fn(() => Promise.resolve(Probe));
    const Dialog = lazyDialog(load);
    render(<Dialog open={false} />);
    expect(screen.queryByTestId("probe")).toBeNull();
  });

  it("stays mounted after it closes, so exit animations and focus return still run", async () => {
    const Dialog = lazyDialog(() => Promise.resolve(Probe));
    const { rerender } = render(<Dialog open />);
    expect((await screen.findByTestId("probe")).dataset.open).toBe("true");

    rerender(<Dialog open={false} />);
    expect(screen.getByTestId("probe").dataset.open).toBe("false");
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
