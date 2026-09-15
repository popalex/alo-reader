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
  // Changing this resets the "already marked" watermark — the caller passes the
  // search state, so entering/leaving a search (which swaps the entries array
  // under the same mount) doesn't skip or mis-mark rows.
  resetKey?: unknown,
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
  // Which entries have already been marked, by id rather than by position.
  //
  // An index watermark goes stale the moment the array shifts, and it shifts often:
  // usePendingFeedPolling invalidates ["entries"] when a new feed lands, the offline
  // replay drain invalidates it, mark-all-read invalidates it, and so does `r`. Every
  // prepended entry then sits below the watermark and can never be marked read by
  // scrolling — it stays unread forever.
  const markedIds = useRef<Set<number>>(new Set());
  useEffect(() => {
    markedIds.current = new Set();
  }, [resetKey]);

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
        // Nothing measured yet (a settle that lands between renders): a scroll
        // position tells us nothing about which rows are above the fold.
        if (items.length === 0) return;

        // First index whose bottom is still below the top edge = first visible;
        // everything before it has scrolled fully above.
        //
        // The fallback when no measured row reaches past the top is the last
        // measured row, NOT es.length: defaulting to the end of the list means one
        // odd settle marks every entry in the stream read, including thousands that
        // were never rendered. Combined with an id set that keeps looking for new
        // work, that turns into "the whole stream is read" rather than a single
        // mistake.
        let firstVisible = items[items.length - 1].index + 1;
        for (const it of items) {
          if (it.start + it.size > top) {
            firstVisible = it.index;
            break;
          }
        }
        const ids: number[] = [];
        for (let i = 0; i < firstVisible; i++) {
          const e = es[i];
          if (e && !e.is_read && !markedIds.current.has(e.id)) {
            ids.push(e.id);
            markedIds.current.add(e.id);
          }
        }
        if (ids.length === 0) return;

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
