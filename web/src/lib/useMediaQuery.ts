// Reactive CSS media query. Initialized synchronously from matchMedia so there's
// no wrong-layout flash on first paint (SPA, no SSR).

import { useEffect, useState } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/** The app's mobile breakpoint (matches the CSS @media max-width: 768px). */
export function useIsMobile(): boolean {
  return useMediaQuery("(max-width: 768px)");
}
