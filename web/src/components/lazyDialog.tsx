// Code-split a dialog out of the initial bundle without changing how it behaves.
//
// Each dialog is only needed after a click, but Radix Dialog and the dialog bodies
// cost ~30 kB of startup JS. The wrapper renders nothing until the dialog is first
// opened, then loads it and keeps it mounted for good: unmounting on close would cut
// off the exit animations (MobileSidebar styles [data-state="closed"]) and Radix's
// focus return. There is no idle prefetch: measured under Lighthouse, fetching the
// chunks at idle landed inside the load window and cost more than it saved.

import { type ComponentType, lazy, Suspense, useState } from "react";

interface DialogProps {
  open: boolean;
}

export function lazyDialog<P extends DialogProps>(
  load: () => Promise<ComponentType<P>>,
): ComponentType<P> {
  // lazy() types its result with ref attributes, which a generic P cannot satisfy.
  // None of these dialogs takes a ref, so narrowing back to ComponentType<P> is safe.
  const Lazy = lazy(() =>
    load().then((component) => ({ default: component })),
  ) as unknown as ComponentType<P>;

  function LazyDialog(props: P) {
    const [opened, setOpened] = useState(props.open);
    // Adjusting state during render, not in an effect: the dialog must start
    // loading in the same render that asks for it to be open.
    if (props.open && !opened) setOpened(true);
    if (!opened) return null;
    return (
      <Suspense fallback={null}>
        <Lazy {...props} />
      </Suspense>
    );
  }
  return LazyDialog;
}
