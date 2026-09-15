// The single global keyboard handler (WP-12). One window-level keydown listener
// dispatches to the actions the caller supplies, keyed by binding id. It:
//   - ignores events originating in text fields (input/textarea/select/
//     contenteditable) so typing is never hijacked;
//   - leaves browser/OS shortcuts alone (Ctrl/Meta/Alt) but allows Shift, which
//     "A" and "?" need;
//   - supports `g`-prefixed chords with a 1s window (a non-matching second key,
//     or the timeout, silently cancels the chord).
// Everything it can do is derived from bindings.ts, so the map stays the single
// source of truth. Actions are read through a ref so the listener is attached
// once, yet always calls the latest closures.

import { useEffect, useRef } from "react";

import { CHORD_PREFIXES, matchChord, matchKey, type BindingId } from "./bindings";

export type KeyboardActions = Partial<Record<BindingId, () => void>>;

const CHORD_TIMEOUT_MS = 1000;

function isTextTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

// Controls the browser activates with Enter or Space. Clicking them IS the default
// action of that keydown, so preventing it is the same as breaking the control.
const ACTIVATABLE = "button, a[href], summary, [role='button'], [role='link'], [role='menuitem']";

function isActivationKeyOnControl(e: KeyboardEvent): boolean {
  if (e.key !== "Enter" && e.key !== " ") return false;
  return e.target instanceof HTMLElement && e.target.closest(ACTIVATABLE) !== null;
}

export function useKeyboard(actions: KeyboardActions, enabled = true): void {
  const actionsRef = useRef(actions);
  actionsRef.current = actions;

  useEffect(() => {
    if (!enabled) return;

    let chord: string | null = null;
    let chordTimer: number | undefined;

    const clearChord = () => {
      chord = null;
      if (chordTimer !== undefined) window.clearTimeout(chordTimer);
      chordTimer = undefined;
    };

    const run = (id: BindingId, e: KeyboardEvent) => {
      const fn = actionsRef.current[id];
      if (!fn) return;
      e.preventDefault();
      fn();
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (isTextTarget(e.target)) return;
      // Enter is bound to "open", and run() preventDefaults everything, so without
      // this a focused button or link could not be activated by keyboard at all:
      // Tab to Subscribe, press Enter, and the reader opened an article instead of
      // the dialog. Entry rows are role="listitem", so they still get Enter.
      if (isActivationKeyOnControl(e)) return;

      // Resolving a pending chord: the previous key was a prefix (e.g. "g").
      if (chord) {
        const prefix = chord;
        clearChord();
        const id = matchChord(prefix, e.key);
        if (id) run(id, e);
        return;
      }

      // Opening a chord window.
      if (CHORD_PREFIXES.has(e.key)) {
        chord = e.key;
        chordTimer = window.setTimeout(clearChord, CHORD_TIMEOUT_MS);
        e.preventDefault();
        return;
      }

      const id = matchKey(e.key);
      if (id) run(id, e);
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      clearChord();
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [enabled]);
}
