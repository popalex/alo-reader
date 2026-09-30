// The reading pane: renders the selected entry's content_html.
// Content is sanitized server-side at ingest (nh3, strict allowlist), and then
// sanitized again here with DOMPurify as defense-in-depth — so a single backend
// regression, or a pre-sanitization row imported by a migration, can't become
// stored XSS with full session/token access. Images are made lazy after render
// and constrained by CSS. Marking read on open is WP-11.

import { useEffect, useMemo, useRef } from "react";

import { Check, ChevronLeft, ChevronRight, Circle, ExternalLink, Star } from "lucide-react";

import { useSetEntryState } from "../../api/mutations";
import { useEntry, useSubscriptions } from "../../api/queries";
import { useOnline } from "../../app/offline/useOffline";
import { markUiEvent } from "../../app/traceUiAction";
import { ErrorBoundary } from "../../components/ErrorBoundary";
import { Favicon } from "../../components/Favicon";
import { useSanitizer } from "../../lib/sanitize";
import { formatDateTime } from "../../lib/time";
import { safeExternalUrl } from "../../lib/url";
import { adjacentEntry, useSelection } from "./selection";
import styles from "./ReaderPane.module.css";

export function ReaderPane() {
  const subs = useSubscriptions();
  const { openId, close, open, readingOrder } = useSelection();
  const articleRef = useRef<HTMLElement>(null);
  const next = adjacentEntry(readingOrder, openId, 1);

  // The article element is reused from one entry to the next: start each at the top,
  // or "Next article" would open the next one scrolled to where this one ended.
  useEffect(() => {
    articleRef.current?.scrollTo({ top: 0 });
  }, [openId]);

  // The end of an article offers the next one in the list, marked read on open like
  // a click in the list. On a phone it is the way on without going Back.
  const openNext = () => {
    if (!next) return;
    markUiEvent("ui.open_article", { "alo.entry.id": next.id });
    open(next.id);
    if (!next.is_read) setState.mutate({ ids: [next.id], read: true });
  };
  const query = useEntry(openId);
  const online = useOnline();
  const setState = useSetEntryState();
  const contentRef = useRef<HTMLDivElement>(null);
  // Defense-in-depth: re-sanitize the already-nh3-cleaned HTML in the browser.
  // No sanitizer yet (first article, chunk still loading) means no content yet.
  const { sanitize, failed: sanitizerFailed } = useSanitizer(Boolean(query.data?.content_html));
  const html = useMemo(
    () =>
      sanitize && query.data?.content_html ? sanitize(query.data.content_html) : undefined,
    [sanitize, query.data?.content_html],
  );

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
  // Entries stored before the parser started rejecting them can still carry a
  // javascript: or data: URL, and React only refuses those in development builds.
  const safeUrl = safeExternalUrl(entry.url);
  // EntryDetail carries no icon, so without this lookup the reader always drew the
  // coloured initial while the list row beside it showed the real favicon.
  const iconUrl = subs.data?.find((s) => s.feed_id === entry.feed_id)?.icon_url ?? undefined;
  const meta = [entry.author, entry.published_at ? formatDateTime(entry.published_at) : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <article className={styles.reader} ref={articleRef}>
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
          {safeUrl ? (
            <a className={styles.action} href={safeUrl} target="_blank" rel="noopener noreferrer">
              <ExternalLink size={14} />
              <span>Open original</span>
            </a>
          ) : null}
        </div>
      </div>
      <header className={styles.header}>
        <div className={styles.source}>
          <Favicon title={entry.feed_title} iconUrl={iconUrl} />
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
        {sanitizerFailed ? (
          <div className={styles.state} role="alert">
            Couldn’t load the article viewer. Reload the page to try again.
          </div>
        ) : (
          <div
            ref={contentRef}
            className={styles.content}
            // nh3 at ingest + DOMPurify here (see the file header) — double-sanitized.
            dangerouslySetInnerHTML={{ __html: html ?? "" }}
          />
        )}
      </ErrorBoundary>
      {next ? (
        <div className={styles.next}>
          <button type="button" className={styles.nextBtn} onClick={openNext}>
            <span className={styles.nextText}>
              <span className={styles.nextLabel}>Next article</span>
              <span className={styles.nextTitle}>{next.title || "Untitled"}</span>
            </span>
            <ChevronRight size={18} aria-hidden="true" />
          </button>
        </div>
      ) : null}
    </article>
  );
}
