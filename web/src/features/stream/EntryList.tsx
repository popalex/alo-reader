// The inbox: a virtualized, newest-first list of entries with infinite cursor
// pagination. Rows show feed favicon, feed name, title, summary and relative
// time; unread rows are bold, read rows dim (DESIGN.md §1.7). The list is the
// keyboard model's home (WP-12): it owns the global handler, since it has the
// entries, the virtualizer (scroll-into-view), selection and the mutations.
// A cursor row (j/k) carries a visible ring; opening (o/Enter/click) drives the
// reading pane and marks read.

import { useEffect, useMemo, useRef, useState } from "react";

import { useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { CheckCheck, CircleAlert, List as ListIcon, RefreshCw, Rows3, Search, Star } from "lucide-react";

import { useMarkStreamRead, useSetEntryState } from "../../api/mutations";
import { useStreamEntries, useSubscriptions } from "../../api/queries";
import { ThemeToggle } from "../../app/ThemeToggle";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Favicon } from "../../components/Favicon";
import { KeyboardHelp } from "../../keyboard/KeyboardHelp";
import { useKeyboard, type KeyboardActions } from "../../keyboard/useKeyboard";
import type { StreamDescriptor } from "../../lib/streams";
import { formatDateTime, relativeTime } from "../../lib/time";
import { useDensity, type Density } from "./density";
import { useScrollReadMarker } from "./useScrollReadMarker";
import { useSelection } from "./selection";
import styles from "./EntryList.module.css";

function DensityToggle({ value, onChange }: { value: Density; onChange: (d: Density) => void }) {
  return (
    <div className={styles.density} role="group" aria-label="List density">
      <button
        type="button"
        className={styles.densityOpt}
        data-active={value === "list"}
        aria-pressed={value === "list"}
        aria-label="Compact rows"
        title="Compact rows"
        onClick={() => onChange("list")}
      >
        <ListIcon size={15} />
      </button>
      <button
        type="button"
        className={styles.densityOpt}
        data-active={value === "expanded"}
        aria-pressed={value === "expanded"}
        aria-label="Expanded rows"
        title="Expanded rows"
        onClick={() => onChange("expanded")}
      >
        <Rows3 size={15} />
      </button>
    </div>
  );
}

function EmptyList({ starred }: { starred: boolean }) {
  return (
    <div className={styles.empty}>
      <p className={styles.emptyTitle}>{starred ? "No starred articles" : "No articles yet"}</p>
      <p className={styles.emptyBody}>
        {starred
          ? "Star an article and it will be kept here."
          : "Articles will appear here as your feeds update, newest first."}
      </p>
    </div>
  );
}

export function EntryList({ stream, title }: { stream: StreamDescriptor; title: string }) {
  const [density, setDensity] = useDensity();
  const { cursorId, openId, setCursor, open, close } = useSelection();
  const setState = useSetEntryState();
  const markStreamRead = useMarkStreamRead(stream);
  const qc = useQueryClient();
  const navigate = useNavigate();

  const [helpOpen, setHelpOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const subs = useSubscriptions();
  const iconByFeed = useMemo(() => {
    const m = new Map<number, string | null>();
    for (const s of subs.data ?? []) m.set(s.feed_id, s.icon_url);
    return m;
  }, [subs.data]);

  const query = useStreamEntries(stream, "all");
  const entries = useMemo(
    () => query.data?.pages.flatMap((p) => p.entries) ?? [],
    [query.data],
  );

  // State-backed ref so the virtualizer re-initializes once the scroll element
  // mounts (a plain useRef doesn't trigger a render, which can leave the list
  // rendering zero rows until the first resize/scroll).
  const [scrollEl, setScrollEl] = useState<HTMLDivElement | null>(null);
  const virtualizer = useVirtualizer({
    count: entries.length,
    getScrollElement: () => scrollEl,
    estimateSize: () => (density === "expanded" ? 92 : 46),
    overscan: 10,
    getItemKey: (i) => entries[i]?.id ?? i,
  });

  // Fetch the next page as the tail of the list scrolls into view.
  const items = virtualizer.getVirtualItems();
  const lastIndex = items.length ? items[items.length - 1].index : 0;
  useEffect(() => {
    if (
      lastIndex >= entries.length - 8 &&
      query.hasNextPage &&
      !query.isFetchingNextPage
    ) {
      void query.fetchNextPage();
    }
  }, [lastIndex, entries.length, query]);

  useScrollReadMarker(scrollEl, virtualizer, entries);

  // Open an entry and mark it read (mark-read-on-open, WP-11).
  const openEntry = (entry: { id: number; is_read: boolean }) => {
    open(entry.id);
    if (!entry.is_read) setState.mutate({ ids: [entry.id], read: true });
  };

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["entries"] });
    void qc.invalidateQueries({ queryKey: ["counts"] });
  };

  const doMarkAllRead = () => {
    const maxId = entries[0]?.id; // newest observed entry bounds the action
    if (maxId != null) markStreamRead.mutate(maxId);
  };

  // Keyboard model (WP-12). Actions operate on the cursor row; they read the
  // latest `entries`/`cursorId` because the map is rebuilt each render.
  const cursorIndex = cursorId == null ? -1 : entries.findIndex((e) => e.id === cursorId);

  // Move the keyboard cursor, scroll it into view and take DOM focus (so the
  // ring is real focus and screen readers announce the row).
  const focusRowSoon = (index: number) => {
    requestAnimationFrame(() => {
      scrollEl?.querySelector<HTMLElement>(`[data-index="${index}"]`)?.focus();
    });
  };
  const moveCursor = (index: number) => {
    const e = entries[index];
    if (!e) return;
    setCursor(e.id);
    virtualizer.scrollToIndex(index, { align: "auto" });
    focusRowSoon(index);
  };

  const actions: KeyboardActions = {
    next: () => moveCursor(cursorIndex < 0 ? 0 : Math.min(cursorIndex + 1, entries.length - 1)),
    prev: () => moveCursor(cursorIndex < 0 ? 0 : Math.max(cursorIndex - 1, 0)),
    open: () => {
      const e = cursorIndex < 0 ? entries[0] : entries[cursorIndex];
      if (!e) return;
      if (openId === e.id) {
        close();
        focusRowSoon(entries.findIndex((x) => x.id === e.id));
      } else {
        openEntry(e);
      }
    },
    openOriginal: () => {
      const e = entries[cursorIndex];
      if (e?.url) window.open(e.url, "_blank", "noopener,noreferrer");
    },
    toggleRead: () => {
      const e = entries[cursorIndex];
      if (e) setState.mutate({ ids: [e.id], read: !e.is_read });
    },
    star: () => {
      const e = entries[cursorIndex];
      if (e) setState.mutate({ ids: [e.id], starred: !e.is_starred });
    },
    markAllRead: () => {
      if (entries.length > 0) setConfirmOpen(true);
    },
    refresh,
    goAll: () => void navigate({ to: "/" }),
    goStarred: () => void navigate({ to: "/starred" }),
    focusSearch: () => searchRef.current?.focus(),
    help: () => setHelpOpen(true),
  };
  // The global handler stands down while a modal owns the keyboard.
  useKeyboard(actions, !helpOpen && !confirmOpen);

  const feedError =
    stream.kind === "feed" ? (subs.data?.find((s) => s.id === stream.id)?.last_error ?? null) : null;

  let body: React.ReactNode;
  if (query.isPending) {
    body = (
      <div className={styles.fill}>
        <div className={styles.state}>Loading articles…</div>
      </div>
    );
  } else if (query.isError) {
    body = (
      <div className={styles.fill}>
        <div className={styles.state} role="alert">
          <CircleAlert size={16} /> Couldn&rsquo;t load articles.
        </div>
      </div>
    );
  } else if (entries.length === 0) {
    body = (
      <div className={styles.fill}>
        <EmptyList starred={stream.kind === "starred"} />
      </div>
    );
  } else {
    body = (
      <div ref={setScrollEl} className={styles.scroll} data-testid="entry-scroll" tabIndex={0}>
        <div
          className={styles.viewport}
          role="list"
          aria-label={`${title} articles`}
          style={{ height: virtualizer.getTotalSize() }}
        >
          {items.map((vi) => {
            const e = entries[vi.index];
            return (
              <div
                key={vi.key}
                role="listitem"
                tabIndex={-1}
                data-index={vi.index}
                ref={virtualizer.measureElement}
                className={styles.row}
                data-density={density}
                data-read={e.is_read || undefined}
                data-selected={openId === e.id || undefined}
                data-cursor={cursorId === e.id || undefined}
                aria-current={openId === e.id}
                onClick={() => {
                  setCursor(e.id);
                  openEntry(e);
                }}
                style={{ transform: `translateY(${vi.start}px)` }}
              >
                <span className={styles.dot} aria-hidden="true" />
                <span className={styles.fav}>
                  <Favicon title={e.feed_title} iconUrl={iconByFeed.get(e.feed_id)} />
                </span>
                <span className={styles.feed}>{e.feed_title}</span>
                <span className={styles.rowtitle}>{e.title}</span>
                <span className={styles.summary}>{e.summary}</span>
                <time
                  className={styles.time}
                  dateTime={e.created_at}
                  title={formatDateTime(e.published_at ?? e.created_at)}
                >
                  {e.is_starred ? <Star className={styles.star} size={12} /> : null}
                  {relativeTime(e.created_at)}
                </time>
              </div>
            );
          })}
        </div>
        {query.isFetchingNextPage ? <div className={styles.more}>Loading more…</div> : null}
      </div>
    );
  }

  return (
    <section className={styles.list} aria-label={title}>
      <header className={styles.head}>
        <h1 className={styles.title}>{title}</h1>
        <div className={styles.controls}>
          <button
            type="button"
            className={styles.toolBtn}
            title="Refresh"
            aria-label="Refresh"
            onClick={refresh}
          >
            <RefreshCw size={15} />
          </button>
          <button
            type="button"
            className={styles.toolBtn}
            title="Mark all read"
            aria-label="Mark all read"
            onClick={() => setConfirmOpen(true)}
            disabled={entries.length === 0}
          >
            <CheckCheck size={15} />
          </button>
          <span className={styles.sep} />
          <DensityToggle value={density} onChange={setDensity} />
          <ThemeToggle />
        </div>
      </header>
      <div className={styles.searchBar}>
        <Search size={14} className={styles.searchIcon} aria-hidden="true" />
        {/* Search executes in WP-13; the input exists now so `/` has a target. */}
        <input
          ref={searchRef}
          type="search"
          className={styles.searchInput}
          placeholder="Search articles"
          aria-label="Search articles"
          readOnly
          title="Search is coming soon"
          onKeyDown={(e) => {
            if (e.key === "Escape") e.currentTarget.blur();
          }}
        />
      </div>
      {feedError ? (
        <div className={styles.errorBanner} role="alert">
          <CircleAlert size={15} />
          <span>This feed failed to update: {feedError}</span>
        </div>
      ) : null}
      {body}

      <KeyboardHelp open={helpOpen} onOpenChange={setHelpOpen} />
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Mark all as read?"
        body={`Every article in ${title} will be marked as read. This can’t be undone.`}
        confirmLabel="Mark all read"
        onConfirm={doMarkAllRead}
      />
    </section>
  );
}
