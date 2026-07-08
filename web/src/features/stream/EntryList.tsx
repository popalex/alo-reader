// The inbox: a virtualized, newest-first list of entries with infinite cursor
// pagination. Rows show feed favicon, feed name, title, summary and relative
// time; unread rows are bold, read rows dim (DESIGN.md §1.7). Selecting a row
// drives the reading pane. Marking read/refresh is WP-11; keyboard is WP-12.

import { useEffect, useMemo, useRef } from "react";

import { useVirtualizer } from "@tanstack/react-virtual";
import { CircleAlert, List as ListIcon, Rows3, Star } from "lucide-react";

import { useStreamEntries, useSubscriptions } from "../../api/queries";
import { ThemeToggle } from "../../app/ThemeToggle";
import { Favicon } from "../../components/Favicon";
import type { StreamDescriptor } from "../../lib/streams";
import { formatDateTime, relativeTime } from "../../lib/time";
import { useDensity, type Density } from "./density";
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
  const { selectedId, select } = useSelection();

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

  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: entries.length,
    getScrollElement: () => scrollRef.current,
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
      <div ref={scrollRef} className={styles.scroll}>
        <div className={styles.viewport} style={{ height: virtualizer.getTotalSize() }}>
          {items.map((vi) => {
            const e = entries[vi.index];
            return (
              <button
                key={vi.key}
                type="button"
                data-index={vi.index}
                ref={virtualizer.measureElement}
                className={styles.row}
                data-density={density}
                data-read={e.is_read || undefined}
                data-selected={selectedId === e.id || undefined}
                aria-current={selectedId === e.id}
                onClick={() => select(e.id)}
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
              </button>
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
          <DensityToggle value={density} onChange={setDensity} />
          <ThemeToggle />
        </div>
      </header>
      {body}
    </section>
  );
}
