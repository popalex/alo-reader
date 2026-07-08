// Mark-read-on-scroll-past (WP-11). Entries scrolled fully above the viewport
// get marked read, batched into one POST /entries/state per settle.
//
// Uses the scroll position + the virtualizer's measured range rather than a
// per-row IntersectionObserver: with a virtualized list rows constantly
// mount/unmount, which makes per-row observers leak observed detached nodes and
// miss fast scroll-throughs. The range read is deterministic and leak-free.

import { useEffect, useRef } from "react";

import type { EntryListItem } from "../../api/endpoints";
import { useSetEntryState } from "../../api/mutations";

const SETTLE_MS = 600; // a row must sit above the fold this long before marking
const CHUNK = 500; // POST /entries/state caps ids at 1000

interface RangeVirtualizer {
  getVirtualItems: () => Array<{ index: number; start: number; size: number }>;
}

export function useScrollReadMarker(
  scrollEl: HTMLElement | null,
  virtualizer: RangeVirtualizer,
  entries: EntryListItem[],
): void {
  const setState = useSetEntryState();
  // Everything the listener needs goes through refs so the effect depends only
  // on scrollEl — otherwise the mutation's fresh identity each render would
  // re-run the effect and clear the pending settle timer mid-scroll.
  const setStateRef = useRef(setState);
  setStateRef.current = setState;
  const entriesRef = useRef(entries);
  entriesRef.current = entries;
  const virtualizerRef = useRef(virtualizer);
  virtualizerRef.current = virtualizer;
  // Highest index already marked (exclusive). Persists across paging; resets
  // when the list remounts per stream.
  const markedUpTo = useRef(0);

  useEffect(() => {
    const el = scrollEl;
    if (!el) return;
    let timer: number | undefined;

    const onScroll = () => {
      if (timer) clearTimeout(timer);
      timer = window.setTimeout(() => {
        const top = el.scrollTop;
        const items = virtualizerRef.current.getVirtualItems();
        const es = entriesRef.current;

        // First index whose bottom is still below the top edge = first visible;
        // everything before it has scrolled fully above.
        let firstVisible = es.length;
        for (const it of items) {
          if (it.start + it.size > top) {
            firstVisible = it.index;
            break;
          }
        }
        if (firstVisible <= markedUpTo.current) return;

        const ids: number[] = [];
        for (let i = markedUpTo.current; i < firstVisible; i++) {
          const e = es[i];
          if (e && !e.is_read) ids.push(e.id);
        }
        markedUpTo.current = firstVisible;

        for (let i = 0; i < ids.length; i += CHUNK) {
          setStateRef.current.mutate({ ids: ids.slice(i, i + CHUNK), read: true });
        }
      }, SETTLE_MS);
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
      if (timer) clearTimeout(timer);
    };
  }, [scrollEl]);
}
