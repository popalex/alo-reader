// The label rail: fixed views (All / Starred) plus collapsible folders, each
// listing its feeds with an unread badge and an error dot. Unread feeds read
// bold with a right-aligned count (DESIGN.md §1.7). Data comes from /folders,
// /subscriptions and /counts via TanStack Query; the active stream is derived
// from the router so links highlight themselves.

import { useMemo, useState } from "react";

import { Link } from "@tanstack/react-router";
import { ChevronDown, Inbox, Plus, Star } from "lucide-react";

import type { Subscription } from "../../api/endpoints";
import { useCounts, useFolders, useSubscriptions } from "../../api/queries";
import { pushToast } from "../../app/toast";
import styles from "./Sidebar.module.css";

/** Stable pseudo-colour for a favicon fallback, derived from the feed title. */
function faviconHue(text: string): number {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0;
  return h % 360;
}

function Favicon({ sub }: { sub: Subscription }) {
  const label = sub.title || sub.site_url || "?";
  if (sub.icon_url) {
    return <img className={styles.fav} src={sub.icon_url} alt="" width={16} height={16} loading="lazy" />;
  }
  return (
    <span
      className={styles.favLetter}
      style={{ background: `hsl(${faviconHue(label)} 42% 42%)` }}
      aria-hidden="true"
    >
      {label.charAt(0).toUpperCase()}
    </span>
  );
}

function FeedLink({ sub, unread }: { sub: Subscription; unread: number }) {
  const base = unread > 0 ? `${styles.feed} ${styles.feedUnread}` : styles.feed;
  return (
    <Link
      to="/feed/$id"
      params={{ id: String(sub.id) }}
      className={base}
      activeProps={{ className: `${base} ${styles.active}` }}
    >
      <Favicon sub={sub} />
      <span className={styles.name}>{sub.title || "Untitled feed"}</span>
      {sub.last_error ? <span className={styles.errorDot} title="This feed failed to update" /> : null}
      {unread > 0 ? <span className={styles.count}>{unread}</span> : null}
    </Link>
  );
}

export function Sidebar() {
  const folders = useFolders();
  const subs = useSubscriptions();
  const counts = useCounts();
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(() => new Set<number>());

  const unreadBySub = useMemo(() => {
    const m = new Map<number, number>();
    for (const s of counts.data?.subscriptions ?? []) m.set(s.id, s.unread);
    return m;
  }, [counts.data]);

  const { grouped, ungrouped } = useMemo(() => {
    const byFolder = new Map<number, Subscription[]>();
    const none: Subscription[] = [];
    for (const s of subs.data ?? []) {
      if (s.folder_id == null) none.push(s);
      else {
        const arr = byFolder.get(s.folder_id) ?? [];
        arr.push(s);
        byFolder.set(s.folder_id, arr);
      }
    }
    return { grouped: byFolder, ungrouped: none };
  }, [subs.data]);

  const sortedFolders = useMemo(
    () =>
      [...(folders.data ?? [])].sort(
        (a, b) => a.position - b.position || a.name.localeCompare(b.name),
      ),
    [folders.data],
  );

  const totalUnread = counts.data?.total_unread ?? 0;
  const loading = subs.isPending || folders.isPending || counts.isPending;

  function toggle(id: number) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const byTitle = (a: Subscription, b: Subscription) => (a.title || "").localeCompare(b.title || "");
  const folderUnread = (feeds: Subscription[]) =>
    feeds.reduce((sum, f) => sum + (unreadBySub.get(f.id) ?? 0), 0);

  return (
    <aside className={styles.side}>
      <div className={styles.head}>
        <span className={styles.logo}>
          alo<span className={styles.dot}>.</span>
        </span>
        <button
          type="button"
          className={styles.subscribe}
          title="Subscribe to a feed"
          onClick={() => pushToast("Adding subscriptions lands in an upcoming update.", "info")}
        >
          <Plus size={15} />
          <span>Subscribe</span>
        </button>
      </div>

      <nav className={styles.views} aria-label="Views">
        <Link
          to="/"
          activeOptions={{ exact: true }}
          className={styles.view}
          activeProps={{ className: `${styles.view} ${styles.active}` }}
        >
          <Inbox size={16} className={styles.viewIcon} />
          <span>All items</span>
          {totalUnread > 0 ? <span className={styles.count}>{totalUnread}</span> : null}
        </Link>
        <Link
          to="/starred"
          className={styles.view}
          activeProps={{ className: `${styles.view} ${styles.active}` }}
        >
          <Star size={16} className={styles.viewIcon} />
          <span>Starred</span>
        </Link>
      </nav>

      {loading ? (
        <div className={styles.status}>Loading feeds…</div>
      ) : (
        <div className={styles.folders}>
          {sortedFolders.map((folder) => {
            const feeds = (grouped.get(folder.id) ?? []).slice().sort(byTitle);
            const isCollapsed = collapsed.has(folder.id);
            const fUnread = folderUnread(feeds);
            return (
              <div className={styles.folder} key={folder.id}>
                <div className={styles.folderHead}>
                  <button
                    type="button"
                    className={styles.chevron}
                    aria-expanded={!isCollapsed}
                    aria-label={isCollapsed ? `Expand ${folder.name}` : `Collapse ${folder.name}`}
                    onClick={() => toggle(folder.id)}
                  >
                    <ChevronDown size={13} data-collapsed={isCollapsed || undefined} />
                  </button>
                  <Link
                    to="/folder/$id"
                    params={{ id: String(folder.id) }}
                    className={styles.folderName}
                    activeProps={{ className: `${styles.folderName} ${styles.folderActive}` }}
                  >
                    {folder.name}
                  </Link>
                  {fUnread > 0 ? <span className={styles.count}>{fUnread}</span> : null}
                </div>
                {!isCollapsed &&
                  feeds.map((sub) => (
                    <FeedLink key={sub.id} sub={sub} unread={unreadBySub.get(sub.id) ?? 0} />
                  ))}
              </div>
            );
          })}

          {ungrouped.length > 0 && (
            <div className={styles.folder}>
              {ungrouped
                .slice()
                .sort(byTitle)
                .map((sub) => (
                  <FeedLink key={sub.id} sub={sub} unread={unreadBySub.get(sub.id) ?? 0} />
                ))}
            </div>
          )}

          {sortedFolders.length === 0 && ungrouped.length === 0 && (
            <div className={styles.status}>No feeds yet. Subscribe to get started.</div>
          )}
        </div>
      )}
    </aside>
  );
}
