import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BINDINGS } from "../src/keyboard/bindings";
import { KeyboardHelp } from "../src/keyboard/KeyboardHelp";
import { useKeyboard, type KeyboardActions } from "../src/keyboard/useKeyboard";

function press(key: string) {
  window.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
}

function Harness({ actions, enabled = true }: { actions: KeyboardActions; enabled?: boolean }) {
  useKeyboard(actions, enabled);
  return null;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("help overlay is generated from the binding table", () => {
  it("lists exactly the bindings, once each — the single source of truth", () => {
    render(<KeyboardHelp open onOpenChange={() => {}} />);

    // Every binding's label appears as a definition row…
    const labels = Array.from(document.querySelectorAll("dd")).map((d) => d.textContent);
    for (const b of BINDINGS) expect(labels).toContain(b.label);
    // …and nothing hand-written beyond the table (one row per binding).
    expect(document.querySelectorAll("dt").length).toBe(BINDINGS.length);
    expect(labels.length).toBe(BINDINGS.length);
    // Chords render each key as its own <kbd> (e.g. g + a).
    expect(screen.getByText("Go to All items").closest("div")?.querySelectorAll("kbd").length).toBe(2);
  });
});

describe("global keyboard handler", () => {
  it("dispatches plain keys to their action", () => {
    const next = vi.fn();
    const star = vi.fn();
    render(<Harness actions={{ next, star }} />);

    press("j");
    press("s");
    expect(next).toHaveBeenCalledTimes(1);
    expect(star).toHaveBeenCalledTimes(1);
  });

  it("resolves g-prefixed chords and cancels on a stray key", () => {
    const goAll = vi.fn();
    const goStarred = vi.fn();
    render(<Harness actions={{ goAll, goStarred }} />);

    press("g");
    press("a");
    expect(goAll).toHaveBeenCalledTimes(1);

    press("g");
    press("x"); // not a chord — silently cancels
    expect(goStarred).not.toHaveBeenCalled();
  });

  it("cancels a chord after the 1s timeout", () => {
    vi.useFakeTimers();
    const goAll = vi.fn();
    render(<Harness actions={{ goAll }} />);

    press("g");
    vi.advanceTimersByTime(1001);
    press("a");
    expect(goAll).not.toHaveBeenCalled();
  });

  it("ignores keys typed into form fields", () => {
    const next = vi.fn();
    render(<Harness actions={{ next }} />);
    const input = document.createElement("input");
    document.body.appendChild(input);

    input.dispatchEvent(new KeyboardEvent("keydown", { key: "j", bubbles: true }));
    expect(next).not.toHaveBeenCalled();
    input.remove();
  });

  it("leaves browser shortcuts (Ctrl/Meta) alone", () => {
    const refresh = vi.fn();
    render(<Harness actions={{ refresh }} />);

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "r", ctrlKey: true }));
    expect(refresh).not.toHaveBeenCalled();
  });

  it("leaves Enter and Space to a focused control", () => {
    // Enter is bound to "open" and run() preventDefaults everything, so without the
    // guard a keyboard user could not activate any button: Tab to Subscribe, press
    // Enter, and the reader opened an article instead of the dialog.
    const open = vi.fn();
    render(<Harness actions={{ open }} />);
    const button = document.createElement("button");
    document.body.appendChild(button);

    const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    button.dispatchEvent(event);

    expect(open).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false); // the browser still gets to click it
    button.remove();
  });

  it("still opens from a focused entry row", () => {
    // Rows are role="listitem" with roving tabindex, not controls: activation is
    // deliberately the global handler's job (see EntryRow's header comment).
    const open = vi.fn();
    render(<Harness actions={{ open }} />);
    const row = document.createElement("div");
    row.setAttribute("role", "listitem");
    row.tabIndex = 0;
    document.body.appendChild(row);

    row.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));

    expect(open).toHaveBeenCalledTimes(1);
    row.remove();
  });

  it("does nothing when disabled (a modal owns the keyboard)", () => {
    const help = vi.fn();
    render(<Harness actions={{ help }} enabled={false} />);

    press("?");
    expect(help).not.toHaveBeenCalled();
  });
});

describe("modal keyboard lock", () => {
  it("any open modal stands the shortcuts down", async () => {
    // EntryList used to gate only on its own two dialogs, so the sidebar's dialogs
    // left every shortcut live underneath them: `A` stacked a second confirm on the
    // first, and `g a` navigated the list behind the dialog.
    const { useAnyModalOpen, useModalKeyboardLock } = await import("../src/keyboard/modalLock");
    const next = vi.fn();

    function Gated({ modal }: { modal: boolean }) {
      useModalKeyboardLock(modal);
      const anyOpen = useAnyModalOpen();
      useKeyboard({ next }, !anyOpen);
      return null;
    }

    const { rerender } = render(<Gated modal={false} />);
    press("j");
    expect(next).toHaveBeenCalledTimes(1);

    rerender(<Gated modal />);
    press("j");
    expect(next).toHaveBeenCalledTimes(1); // still 1: the modal owns the keyboard

    rerender(<Gated modal={false} />);
    press("j");
    expect(next).toHaveBeenCalledTimes(2);
  });
});
