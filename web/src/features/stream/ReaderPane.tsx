// The reading pane: renders the selected entry's sanitized content_html.
// Content is sanitized at ingest (nh3), so it's rendered directly; images are
// made lazy after render and constrained by CSS. Marking read on open is WP-11.

import { useEffect, useRef } from "react";

import { Check, ChevronLeft, Circle, ExternalLink, Star } from "lucide-react";

import { useSetEntryState } from "../../api/mutations";
import { useEntry } from "../../api/queries";
import { useOnline } from "../../app/offline/useOffline";
import { ErrorBoundary } from "../../components/ErrorBoundary";
import { Favicon } from "../../components/Favicon";
import { formatDateTime } from "../../lib/time";
import { useSelection } from "./selection";
import styles from "./ReaderPane.module.css";

export function ReaderPane() {
  const { openId, close } = useSelection();
  const query = useEntry(openId);
  const online = useOnline();
  const setState = useSetEntryState();
  const contentRef = useRef<HTMLDivElement>(null);
  const html = query.data?.content_html;

  // Make feed images lazy/async after each content change (the container is
  // reused across entries, so a ref callback alone wouldn't re-run).
  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    el.querySelectorAll("img").forEach((img) => {
      img.loading = "lazy";
      img.decoding = "async";
      // Feed images often ship without alt text; mark those decorative so they
      // don't read as unlabelled images to assistive tech (WP-12 a11y).
      if (!img.hasAttribute("alt")) img.alt = "";
    });
  }, [html]);

  if (openId == null) {
    return (
      <article className={styles.reader}>
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>Select an article</p>
          <p className={styles.emptyBody}>Choose something from the list to read it here.</p>
        </div>
      </article>
    );
  }

  if (query.isPending) {
    return (
      <article className={styles.reader}>
        <div className={styles.state}>Loading…</div>
      </article>
    );
  }

  if (query.isError || !query.data) {
    return (
      <article className={styles.reader}>
        <div className={styles.state} role="alert">
          {online
            ? "Couldn’t load this article."
            : "You’re offline. Open articles while online to read them here later."}
        </div>
      </article>
    );
  }

  const entry = query.data;
  const meta = [entry.author, entry.published_at ? formatDateTime(entry.published_at) : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <article className={styles.reader}>
      <div className={styles.bar}>
        <button type="button" className={styles.back} onClick={close}>
          <ChevronLeft size={16} /> Back
        </button>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.action}
            data-active={entry.is_starred}
            aria-pressed={entry.is_starred}
            title={entry.is_starred ? "Unstar" : "Star"}
            onClick={() => setState.mutate({ ids: [entry.id], starred: !entry.is_starred })}
          >
            <Star size={15} className={styles.starIcon} />
            <span>{entry.is_starred ? "Starred" : "Star"}</span>
          </button>
          <button
            type="button"
            className={styles.action}
            title={entry.is_read ? "Mark unread" : "Mark read"}
            onClick={() => setState.mutate({ ids: [entry.id], read: !entry.is_read })}
          >
            {entry.is_read ? <Circle size={15} /> : <Check size={15} />}
            <span>{entry.is_read ? "Mark unread" : "Mark read"}</span>
          </button>
          {entry.url ? (
            <a className={styles.action} href={entry.url} target="_blank" rel="noopener noreferrer">
              <ExternalLink size={14} />
              <span>Open original</span>
            </a>
          ) : null}
        </div>
      </div>
      <header className={styles.header}>
        <div className={styles.source}>
          <Favicon title={entry.feed_title} />
          <span>{entry.feed_title}</span>
        </div>
        <h1 className={styles.title}>{entry.title}</h1>
        {meta ? <div className={styles.meta}>{meta}</div> : null}
      </header>
      {/* A malformed article shouldn't take down the list — degrade to a notice,
          reset when a different entry opens. */}
      <ErrorBoundary
        resetKey={entry.id}
        fallback={
          <div className={styles.state} role="alert">
            Couldn’t display this article.
          </div>
        }
      >
        <div
          ref={contentRef}
          className={styles.content}
          // Sanitized at ingest (nh3, strict allowlist) — see DESIGN.md §1.3.
          dangerouslySetInnerHTML={{ __html: entry.content_html }}
        />
      </ErrorBoundary>
    </article>
  );
}
