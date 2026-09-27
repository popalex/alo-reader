// Code-split a dialog out of the initial bundle without changing how it behaves.
//
// Each dialog is only needed after a click, but Radix Dialog and the dialog bodies
// cost ~30 kB of startup JS. The wrapper renders nothing until the dialog is first
// opened, then loads it and keeps it mounted for good: unmounting on close would cut
// off the exit animations (MobileSidebar styles [data-state="closed"]) and Radix's
// focus return. There is no idle prefetch: measured under Lighthouse, fetching the
// chunks at idle landed inside the load window and cost more than it saved.
//
// Loading is explicit rather than React.lazy, because a chunk can fail to load. The
// usual case is a deploy while the app is open: the page still names the old hashed
// chunk, and the new image no longer has it. React.lazy would throw that to the
// nearest error boundary, which for the sidebar's dialogs is the whole app. Here the
// user gets a toast and the dialog stays closed. Only a reload recovers: Chrome
// caches a failed module import for the life of the page and never refetches it.

import { type ComponentType, useEffect, useState } from "react";

import { pushToast } from "../app/toast";

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function lazyDialog<P extends DialogProps>(
  load: () => Promise<ComponentType<P>>,
): ComponentType<P> {
  let loaded: ComponentType<P> | undefined;
  let pending: Promise<ComponentType<P>> | undefined;

  function LazyDialog(props: P) {
    const [Component, setComponent] = useState<ComponentType<P> | undefined>(() => loaded);
    const { open, onOpenChange } = props;

    useEffect(() => {
      if (Component || !open) return;
      let live = true;
      pending ??= load().then(
        (component) => (loaded = component),
        (error: unknown) => {
          pending = undefined; // harmless where the browser does refetch
          throw error;
        },
      );
      pending.then(
        (component) => live && setComponent(() => component),
        () => {
          if (!live) return;
          pushToast("Couldn't open that. Reload the page to get the latest version of the app.");
          onOpenChange(false);
        },
      );
      return () => {
        live = false;
      };
    }, [Component, open, onOpenChange]);

    return Component ? <Component {...props} /> : null;
  }
  return LazyDialog;
}
