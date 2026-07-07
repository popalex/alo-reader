// The two right-hand panes: the article list and the reading pane. Both are
// placeholders in WP-09 — the virtualised list lands in WP-10 and reading in
// WP-10/11. This owns the list header (stream title + theme toggle) and the
// empty states, so the three-pane shell reads as finished.

import { useMemo } from "react";

import { ThemeToggle } from "../../app/ThemeToggle";
import { useFolders, useSubscriptions } from "../../api/queries";
import styles from "./StreamView.module.css";

export type StreamDescriptor =
  | { kind: "all" }
  | { kind: "starred" }
  | { kind: "feed"; id: number }
  | { kind: "folder"; id: number };

function useStreamTitle(stream: StreamDescriptor): string {
  const subs = useSubscriptions();
  const folders = useFolders();
  return useMemo(() => {
    switch (stream.kind) {
      case "all":
        return "All items";
      case "starred":
        return "Starred";
      case "feed":
        return subs.data?.find((s) => s.id === stream.id)?.title || "Feed";
      case "folder":
        return folders.data?.find((f) => f.id === stream.id)?.name || "Folder";
    }
  }, [stream, subs.data, folders.data]);
}

export function StreamView({ stream }: { stream: StreamDescriptor }) {
  const title = useStreamTitle(stream);
  const isStarred = stream.kind === "starred";

  return (
    <div className={styles.panes}>
      <section className={styles.list} aria-label={title}>
        <header className={styles.listHead}>
          <h1 className={styles.listTitle}>{title}</h1>
          <ThemeToggle />
        </header>
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>{isStarred ? "No starred articles" : "Nothing here yet"}</p>
          <p className={styles.emptyBody}>
            {isStarred
              ? "Star an article and it will be kept here."
              : "Articles from your feeds will appear here, newest first. The list arrives in the next update."}
          </p>
        </div>
      </section>

      <article className={styles.reader}>
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>Select an article</p>
          <p className={styles.emptyBody}>Choose something from the list to read it here.</p>
        </div>
      </article>
    </div>
  );
}
