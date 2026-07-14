// The inbox: a virtualized, newest-first list of entries with infinite cursor
// pagination. Rows show feed favicon, feed name, title, summary and relative
// time; unread rows are bold, read rows dim (DESIGN.md §1.7). The list is the
// keyboard model's home (WP-12): it owns the global handler, since it has the
// entries, the virtualizer (scroll-into-view), selection and the mutations.
// A cursor row (j/k) carries a visible ring; opening (o/Enter/click) drives the
// reading pane and marks read. Search (WP-13, DESIGN.md §4.1) reuses this list:
// the `/` search box filters the stream (or all streams) via `q=`, replacing the
// summary with a highlighted ts_headline snippet, still newest-first.

import { useCallback, useEffect, useMemo, useState } from "react";

import { useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { CircleAlert, Loader2 } from "lucide-react";

import type { EntryListItem } from "../../api/endpoints";
import { useMarkStreamRead, useSetEntryState } from "../../api/mutations";
import { usePrefetchEntry, useStreamEntries, useSubscriptions } from "../../api/queries";
import { useOnline } from "../../app/offline/useOffline";
import { useMobileNav } from "../layout/mobileNav";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { KeyboardHelp } from "../../keyboard/KeyboardHelp";
import { useKeyboard, type KeyboardActions } from "../../keyboard/useKeyboard";
import type { StreamDescriptor } from "../../lib/streams";
import { useIsMobile } from "../../lib/useMediaQuery";
import { useDensity } from "./density";
import { EntryListHeader } from "./EntryListHeader";
import { EntryRow } from "./EntryRow";
import { SearchBar } from "./SearchBar";
import { useStreamSearch } from "./useStreamSearch";
import { useScrollReadMarker } from "./useScrollReadMarker";
import { useSelection } from "./selection";
import styles from "./EntryList.module.css";

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
  const { mutate: mutateEntryState } = setState;
  const markStreamRead = useMarkStreamRead(stream);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const online = useOnline();
  const { openSidebar } = useMobileNav();
  const isMobile = useIsMobile();
  const prefetchEntry = usePrefetchEntry();

  const [helpOpen, setHelpOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Search (WP-13) — state + debounce + active-stream derivation live in the hook.
  const search = useStreamSearch(stream);
  const { searching, searchTerm, scopeAll, activeStream, searchRef } = search;

  const subs = useSubscriptions();
  const iconByFeed = useMemo(() => {
    const m = new Map<number, string | null>();
    for (const s of subs.data ?? []) m.set(s.feed_id, s.icon_url);
    return m;
  }, [subs.data]);

  const query = useStreamEntries(activeStream, searching ? searchTerm : undefined);
  const entries = useMemo(() => query.data?.pages.flatMap((p) => p.entries) ?? [], [query.data]);

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

  // Fetch the next page as the tail of the list scrolls into view. Depend on the
  // specific query fields (fetchNextPage is stable) rather than the whole query
  // object, which gets a new identity every render.
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query;
  const items = virtualizer.getVirtualItems();
  const lastIndex = items.length ? items[items.length - 1].index : 0;
  useEffect(() => {
    if (lastIndex >= entries.length - 8 && hasNextPage && !isFetchingNextPage) {
      void fetchNextPage();
    }
  }, [lastIndex, entries.length, hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Scroll-past marks read (WP-11) — but not while searching: paging through search
  // hits shouldn't silently mark them read.
  useScrollReadMarker(scrollEl, virtualizer, searching ? [] : entries, searching);

  // Warm the top of the stream while online so those bodies are cached and open
  // offline without being read first (WP-14). Deferred + cancellable so the burst
  // never competes with the initial load or the reconnect replay; prefetchQuery
  // skips already-fresh ids.
  useEffect(() => {
    if (!online || entries.length === 0) return;
    const ids = entries.slice(0, 25).map((e) => e.id);
    const t = window.setTimeout(() => ids.forEach(prefetchEntry), 1500);
    return () => window.clearTimeout(t);
  }, [entries, online, prefetchEntry]);

  // Open an entry and mark it read (mark-read-on-open, WP-11). Memoized (stable
  // deps) so EntryRow's memo isn't defeated by a fresh handler each render.
  const openEntry = useCallback(
    (entry: { id: number; is_read: boolean }) => {
      open(entry.id);
      if (!entry.is_read) mutateEntryState({ ids: [entry.id], read: true });
    },
    [open, mutateEntryState],
  );
  // Row click / Enter: move the cursor here and open it.
  const activateEntry = useCallback(
    (entry: EntryListItem) => {
      setCursor(entry.id);
      openEntry(entry);
    },
    [setCursor, openEntry],
  );

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["entries"] });
    void qc.invalidateQueries({ queryKey: ["counts"] });
  };

  const doMarkAllRead = () => {
    // Mark the whole stream (no id bound): with publish-date ordering the top row's
    // id is not the max id, so a bound would miss most of the feed.
    markStreamRead.mutate(undefined);
  };

  // Keyboard model (WP-12). Actions operate on the cursor row; they read the
  // latest `entries`/`cursorId` because the map is rebuilt each render.
  const cursorIndex = cursorId == null ? -1 : entries.findIndex((e) => e.id === cursorId);

  // Move the keyboard cursor, scroll it into view and take DOM focus (so the
  // ring is real focus and screen readers announce the row). On a large jump the
  // target row isn't virtualized in yet on the first frame, so retry a few frames.
  const focusRowSoon = (index: number) => {
    let tries = 0;
    const attempt = () => {
      const el = scrollEl?.querySelector<HTMLElement>(`[data-index="${index}"]`);
      if (el) el.focus();
      else if (tries++ < 3) requestAnimationFrame(attempt);
    };
    requestAnimationFrame(attempt);
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
      // Mark-all marks the whole base stream, so it's ambiguous while a search
      // filters the view — disabled then. It also can't be queued offline.
      if (online && !searching && entries.length > 0) setConfirmOpen(true);
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
    stream.kind === "feed"
      ? (subs.data?.find((s) => s.feed_id === stream.id)?.last_error ?? null)
      : null;

  let body: React.ReactNode;
  if (query.isPending) {
    body = (
      <div className={styles.fill}>
        <div className={styles.state}>{searching ? "Searching…" : "Loading articles…"}</div>
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
        {searching ? (
          <div className={styles.empty}>
            <p className={styles.emptyTitle}>No results</p>
            <p className={styles.emptyBody}>
              Nothing matches &ldquo;{searchTerm}&rdquo;
              {scopeAll ? "" : ` in ${title}`}.
            </p>
          </div>
        ) : (
          <EmptyList starred={stream.kind === "starred"} />
        )}
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
              <EntryRow
                key={vi.key}
                entry={e}
                iconUrl={iconByFeed.get(e.feed_id)}
                density={density}
                isOpen={openId === e.id}
                isCursor={cursorId === e.id}
                searching={searching}
                start={vi.start}
                index={vi.index}
                measureElement={virtualizer.measureElement}
                onActivate={activateEntry}
              />
            );
          })}
        </div>
        {isFetchingNextPage ? <div className={styles.more}>Loading more…</div> : null}
      </div>
    );
  }

  return (
    <section className={styles.list} aria-label={title}>
      <EntryListHeader
        title={title}
        density={density}
        setDensity={setDensity}
        online={online}
        searching={searching}
        markPending={markStreamRead.isPending}
        hasEntries={entries.length > 0}
        isMobile={isMobile}
        onOpenSidebar={openSidebar}
        onRefresh={refresh}
        onMarkAllRead={() => setConfirmOpen(true)}
      />
      <SearchBar stream={stream} title={title} search={search} />
      {feedError ? (
        <div className={styles.errorBanner} role="alert">
          <CircleAlert size={15} />
          <span>This feed failed to update: {feedError}</span>
        </div>
      ) : null}
      {markStreamRead.isPending ? (
        <div className={styles.progressBanner} role="status" aria-live="polite">
          <Loader2 size={15} className={styles.spin} />
          <span>Marking all as read…</span>
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
