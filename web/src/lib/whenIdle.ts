// Run a callback once the browser has nothing better to do: after first paint and
// the initial data load, not during them. Used to prefetch lazy chunks so the first
// open of a dialog or article does not wait on the network, without putting that
// code back on the startup path.

export function whenIdle(fn: () => void): void {
  if (typeof window === "undefined") return;
  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(fn, { timeout: 5000 });
  } else {
    setTimeout(fn, 2000);
  }
}
