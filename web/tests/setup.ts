// Vitest setup. jsdom implements neither IndexedDB (offline queue), matchMedia
// (the responsive useMediaQuery hook), nor scrollTo (TanStack Router's scroll
// restoration), so polyfill them for the unit env. scrollTo in particular throws
// an *unhandled* error from an async router effect that fails the whole run even
// when every test passes, so it must be a no-op here.

import "fake-indexeddb/auto";

// jsdom defines scrollTo only as a stub that throws "Not implemented", so replace
// it outright rather than guarding on existence.
window.scrollTo = (() => {}) as typeof window.scrollTo;

if (typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}
