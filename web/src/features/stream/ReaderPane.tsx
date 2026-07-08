// The reading pane: renders the selected entry's sanitized content_html.
// Content is sanitized at ingest (nh3), so it's rendered directly; images are
// made lazy after render and constrained by CSS. Marking read on open is WP-11.

import { useEffect, useRef } from "react";

import { ChevronLeft, ExternalLink } from "lucide-react";

import { useEntry } from "../../api/queries";
import { Favicon } from "../../components/Favicon";
import { formatDateTime } from "../../lib/time";
import { useSelection } from "./selection";
import styles from "./ReaderPane.module.css";

export function ReaderPane() {
  const { selectedId, clear } = useSelection();
  const query = useEntry(selectedId);
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
    });
  }, [html]);

  if (selectedId == null) {
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
          Couldn&rsquo;t load this article.
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
        <button type="button" className={styles.back} onClick={clear}>
          <ChevronLeft size={16} /> Back
        </button>
        {entry.url ? (
          <a className={styles.orig} href={entry.url} target="_blank" rel="noopener noreferrer">
            Open original <ExternalLink size={13} />
          </a>
        ) : null}
      </div>
      <header className={styles.header}>
        <div className={styles.source}>
          <Favicon title={entry.feed_title} />
          <span>{entry.feed_title}</span>
        </div>
        <h1 className={styles.title}>{entry.title}</h1>
        {meta ? <div className={styles.meta}>{meta}</div> : null}
      </header>
      <div
        ref={contentRef}
        className={styles.content}
        // Sanitized at ingest (nh3, strict allowlist) — see DESIGN.md §1.3.
        dangerouslySetInnerHTML={{ __html: entry.content_html }}
      />
    </article>
  );
}
