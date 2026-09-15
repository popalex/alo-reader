// "A modal owns the keyboard" as one app-wide fact instead of a flag per component.
//
// EntryList used to gate the global handler on its own two dialogs, so every other
// modal — add feed, feed settings, the sidebar's delete confirmations — left the
// shortcuts live underneath it: `A` opened a second confirm on top of the first, and
// `g a` navigated the list behind the dialog. Radix traps focus, not keydown
// listeners bound to window.

import { useEffect } from "react";
import { useSyncExternalStore } from "react";

let openCount = 0;
const listeners = new Set<() => void>();

function notify(): void {
  for (const cb of listeners) cb();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

/** Hold the lock for as long as `open` is true. */
export function useModalKeyboardLock(open: boolean): void {
  useEffect(() => {
    if (!open) return;
    openCount += 1;
    notify();
    return () => {
      openCount = Math.max(0, openCount - 1);
      notify();
    };
  }, [open]);
}

/** True while any modal is open. Drives the global keyboard handler. */
export function useAnyModalOpen(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => openCount > 0,
    () => false,
  );
}
