// A single virtualized entry row, split out of EntryList and memoized so a cursor
// or selection change re-renders only the two rows whose state actually flipped —
// not every row in the overscan window. All props are stable references (the entry
// object is stable per id from the query cache; the callbacks are useCallback'd in
// EntryList), which is what makes React.memo effective here.
//
// Accessibility (M4): the row carries roving tabindex — the cursor row is the
// single tab stop — so the list is reachable by Tab and the focused row is a real
// focus target screen readers announce. Activation itself (Enter/o toggles open,
// preserving the documented "open or close" binding) stays with the one global
// keyboard handler, which fires on the focused row; adding a second row-level
// handler would double-fire and break the toggle.

import { memo } from "react";

import { Star } from "lucide-react";

import type { EntryListItem } from "../../api/endpoints";
import { Favicon } from "../../components/Favicon";
import { highlightSnippet } from "../../lib/highlight";
import { formatDateTime, relativeTime } from "../../lib/time";
import type { Density } from "./density";
import styles from "./EntryList.module.css";

interface EntryRowProps {
  entry: EntryListItem;
  iconUrl: string | null | undefined;
  density: Density;
  isOpen: boolean;
  isCursor: boolean;
  searching: boolean;
  start: number;
  index: number;
  measureElement: (el: HTMLElement | null) => void;
  onActivate: (entry: EntryListItem) => void;
}

function EntryRowImpl({
  entry,
  iconUrl,
  density,
  isOpen,
  isCursor,
  searching,
  start,
  index,
  measureElement,
  onActivate,
}: EntryRowProps) {
  return (
    <div
      role="listitem"
      tabIndex={isCursor ? 0 : -1}
      data-index={index}
      ref={measureElement}
      className={styles.row}
      data-density={density}
      data-read={entry.is_read || undefined}
      data-selected={isOpen || undefined}
      data-cursor={isCursor || undefined}
      aria-current={isOpen}
      onClick={() => onActivate(entry)}
      style={{ transform: `translateY(${start}px)` }}
    >
      <span className={styles.dot} aria-hidden="true" />
      <span className={styles.fav}>
        <Favicon title={entry.feed_title} iconUrl={iconUrl} />
      </span>
      <span className={styles.feed}>{entry.feed_title}</span>
      <span className={styles.rowtitle}>{entry.title}</span>
      {searching && entry.snippet ? (
        <span
          className={styles.summary}
          // Safe: highlightSnippet escapes all content, re-allows only <b>.
          dangerouslySetInnerHTML={{ __html: highlightSnippet(entry.snippet) }}
        />
      ) : (
        <span className={styles.summary}>{entry.summary}</span>
      )}
      <time
        className={styles.time}
        dateTime={entry.published_at ?? entry.created_at}
        title={formatDateTime(entry.published_at ?? entry.created_at)}
      >
        {entry.is_starred ? <Star className={styles.star} size={12} /> : null}
        {/* The feed's own publish date; fall back to ingest time only when the feed
            provides none (so a backfilled feed doesn't show every entry as "just now"). */}
        {relativeTime(entry.published_at ?? entry.created_at)}
      </time>
    </div>
  );
}

export const EntryRow = memo(EntryRowImpl);
