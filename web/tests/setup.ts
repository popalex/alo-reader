// Vitest setup. jsdom implements neither IndexedDB (offline queue) nor matchMedia
// (the responsive useMediaQuery hook), so polyfill both for the unit env.

import "fake-indexeddb/auto";

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
