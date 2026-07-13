// The label rail: fixed views (All / Starred) plus collapsible folders, each
// listing its feeds with an unread badge and an error dot. Unread feeds read
// bold with a right-aligned count (DESIGN.md §1.7). Data comes from /folders,
// /subscriptions and /counts via TanStack Query; the active stream is derived
// from the router so links highlight themselves.

import { useMemo, useState } from "react";

import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { ChevronDown, Inbox, Loader2, Pencil, Plus, Settings2, Star, Trash2 } from "lucide-react";

import type { Folder, Subscription } from "../../api/endpoints";
import { useDeleteFolder, useDeleteSubscription, useUpdateFolder } from "../../api/feedMutations";
import { useCounts, useFolders, useSubscriptions } from "../../api/queries";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Favicon } from "../../components/Favicon";
import { AddSubscriptionDialog } from "../subscribe/AddSubscriptionDialog";
import { FeedSettingsDialog } from "../subscribe/FeedSettingsDialog";
import styles from "./Sidebar.module.css";

function FeedLink({
  sub,
  unread,
  onSettings,
}: {
  sub: Subscription;
  unread: number;
  onSettings: (sub: Subscription) => void;
}) {
  const base = unread > 0 ? `${styles.feed} ${styles.feedUnread}` : styles.feed;
  return (
    <div className={styles.feedRow}>
      <Link
        to="/feed/$id"
        params={{ id: String(sub.feed_id) }}
        className={base}
        activeProps={{ className: `${base} ${styles.active}` }}
      >
        <Favicon title={sub.title || sub.site_url || "?"} iconUrl={sub.icon_url} />
        <span className={styles.name}>{sub.title || "Untitled feed"}</span>
        {sub.last_error ? (
          <span className={styles.errorDot} title="This feed failed to update" />
        ) : !sub.last_fetched_at ? (
          <Loader2 size={13} className={styles.fetching} aria-label="Fetching articles…" />
        ) : null}
        {unread > 0 ? <span className={styles.count}>{unread}</span> : null}
      </Link>
      <button
        type="button"
        className={styles.del}
        title="Feed settings"
        aria-label={`Settings for ${sub.title || "this feed"}`}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onSettings(sub);
        }}
      >
        <Settings2 size={13} />
      </button>
    </div>
  );
}

function FolderHeader({
  folder,
  unread,
  isCollapsed,
  onToggle,
  onDelete,
}: {
  folder: Folder;
  unread: number;
  isCollapsed: boolean;
  onToggle: () => void;
  onDelete: (folder: Folder) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(folder.name);
  const rename = useUpdateFolder();

  function commit() {
    setEditing(false);
    const next = name.trim();
    if (next && next !== folder.name) rename.mutate({ id: folder.id, name: next });
    else setName(folder.name);
  }

  return (
    <div className={styles.folderHead}>
      <button
        type="button"
        className={styles.chevron}
        aria-expanded={!isCollapsed}
        aria-label={isCollapsed ? `Expand ${folder.name}` : `Collapse ${folder.name}`}
        onClick={onToggle}
      >
        <ChevronDown size={13} data-collapsed={isCollapsed || undefined} />
      </button>

      {editing ? (
        <input
          className={styles.folderEdit}
          value={name}
          autoFocus
          aria-label={`Rename ${folder.name}`}
          onChange={(e) => setName(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            else if (e.key === "Escape") {
              setName(folder.name);
              setEditing(false);
            }
          }}
        />
      ) : (
        <Link
          to="/folder/$id"
          params={{ id: String(folder.id) }}
          className={styles.folderName}
          activeProps={{ className: `${styles.folderName} ${styles.folderActive}` }}
        >
          {folder.name}
        </Link>
      )}

      {!editing && (
        <div className={styles.folderActions}>
          <button
            type="button"
            className={styles.folderAction}
            title="Rename category"
            aria-label={`Rename ${folder.name}`}
            onClick={() => {
              setName(folder.name);
              setEditing(true);
            }}
          >
            <Pencil size={12} />
          </button>
          <button
            type="button"
            className={styles.folderAction}
            title="Delete category"
            aria-label={`Delete ${folder.name}`}
            onClick={() => onDelete(folder)}
          >
            <Trash2 size={12} />
          </button>
        </div>
      )}

      {unread > 0 && !editing ? <span className={styles.count}>{unread}</span> : null}
    </div>
  );
}

export function Sidebar() {
  const folders = useFolders();
  const subs = useSubscriptions();
  const counts = useCounts();
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(() => new Set<number>());
  const [addOpen, setAddOpen] = useState(false);
  const [settingsSub, setSettingsSub] = useState<Subscription | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Subscription | null>(null);
  const [pendingDeleteFolder, setPendingDeleteFolder] = useState<Folder | null>(null);
  const deleteSub = useDeleteSubscription();
  const deleteFolder = useDeleteFolder();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });

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
          onClick={() => setAddOpen(true)}
        >
          <Plus size={15} />
          <span>Subscribe</span>
        </button>
      </div>

      <AddSubscriptionDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        folders={folders.data ?? []}
      />

      <FeedSettingsDialog
        sub={settingsSub}
        open={settingsSub !== null}
        onOpenChange={(open) => !open && setSettingsSub(null)}
        folders={folders.data ?? []}
        onDelete={setPendingDelete}
      />

      <ConfirmDialog
        open={pendingDeleteFolder !== null}
        onOpenChange={(open) => !open && setPendingDeleteFolder(null)}
        title="Delete this category?"
        body={(() => {
          if (!pendingDeleteFolder) return "";
          const n = grouped.get(pendingDeleteFolder.id)?.length ?? 0;
          return n > 0
            ? `"${pendingDeleteFolder.name}" will be removed. Its ${n} feed${n === 1 ? "" : "s"} will move to Uncategorized.`
            : `The empty category "${pendingDeleteFolder.name}" will be removed.`;
        })()}
        confirmLabel="Delete"
        onConfirm={() => {
          if (pendingDeleteFolder) deleteFolder.mutate(pendingDeleteFolder.id);
        }}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        title="Delete this feed?"
        body={`"${pendingDelete?.title || "Untitled feed"}" will be removed along with its articles and your read/star history. Re-subscribing later starts fresh.`}
        confirmLabel="Delete"
        onConfirm={() => {
          if (!pendingDelete) return;
          const { id, title, feed_id } = pendingDelete;
          deleteSub.mutate(
            { id, title },
            {
              // If we're viewing the feed we just left, go back to All items so the
              // list + reader don't keep showing the removed feed's content.
              onSuccess: () => {
                if (pathname === `/feed/${feed_id}`) void navigate({ to: "/" });
              },
            },
          );
        }}
      />

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
                <FolderHeader
                  folder={folder}
                  unread={fUnread}
                  isCollapsed={isCollapsed}
                  onToggle={() => toggle(folder.id)}
                  onDelete={setPendingDeleteFolder}
                />
                {!isCollapsed &&
                  feeds.map((sub) => (
                    <FeedLink key={sub.id} sub={sub} unread={unreadBySub.get(sub.id) ?? 0} onSettings={setSettingsSub} />
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
                  <FeedLink key={sub.id} sub={sub} unread={unreadBySub.get(sub.id) ?? 0} onSettings={setSettingsSub} />
                ))}
            </div>
          )}

          {sortedFolders.length === 0 && ungrouped.length === 0 && (
            <button type="button" className={styles.empty} onClick={() => setAddOpen(true)}>
              No feeds yet — add your first feed.
            </button>
          )}
        </div>
      )}
    </aside>
  );
}
