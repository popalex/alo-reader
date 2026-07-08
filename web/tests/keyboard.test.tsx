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

  it("does nothing when disabled (a modal owns the keyboard)", () => {
    const help = vi.fn();
    render(<Harness actions={{ help }} enabled={false} />);

    press("?");
    expect(help).not.toHaveBeenCalled();
  });
});
