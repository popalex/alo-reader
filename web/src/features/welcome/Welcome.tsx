// The first screen of an account with no feeds, in place of the list and reader
// panes (StreamView). Most people arriving at a new RSS reader are moving from
// another one, so importing their OPML file is the main action; adding a single
// feed or site comes second.
//
// The import runs from here directly rather than through the add-feed dialog: once
// the first feeds exist this screen gives way to the article list, and the import's
// toast ("Imported N feeds.") outlives that switch where a dialog opened from here
// would not.

import { useState } from "react";

import { FileUp, Loader2, Menu, Plus } from "lucide-react";

import { ApiError } from "../../api/client";
import { useImportOpml, useSubscribeMany } from "../../api/feedMutations";
import { hasPublicSite } from "../../app/instance";
import { useIsMobile } from "../../lib/useMediaQuery";
import { useAddFeed } from "../layout/addFeed";
import { useMobileNav } from "../layout/mobileNav";
import styles from "./Welcome.module.css";

/** A few long-running, varied feeds for someone new to RSS. Picked for staying power
 *  and range, not endorsement. Each address served a working feed when checked
 *  (2026-09-30), and each title is the one the feed gives itself: the title sent on
 *  subscribe is only a placeholder that the first fetch replaces, so any other name
 *  would change in the sidebar right after it was ticked. */
const STARTERS = [
  {
    title: "NASA Image of the Day",
    url: "https://www.nasa.gov/feeds/iotd-feed/",
    about: "A photograph from NASA, most days.",
  },
  {
    title: "xkcd.com",
    url: "https://xkcd.com/atom.xml",
    about: "A webcomic about science, maths and language.",
  },
  {
    title: "BBC News",
    url: "https://feeds.bbci.co.uk/news/rss.xml",
    about: "Top stories from the BBC, through the day.",
  },
  {
    title: "Quanta Magazine",
    url: "https://www.quantamagazine.org/feed/",
    about: "Long reads on mathematics, physics, biology and computing.",
  },
  {
    title: "Hacker News",
    url: "https://news.ycombinator.com/rss",
    about: "The front page of a busy technology link site.",
  },
  {
    title: "kottke.org",
    url: "https://feeds.kottke.org/main",
    about: "A blog of interesting finds from around the web, since 1998.",
  },
];

export function Welcome() {
  const isMobile = useIsMobile();
  const { openSidebar } = useMobileNav();
  const { openAddFeed } = useAddFeed();
  const importer = useImportOpml();
  const [error, setError] = useState<string | null>(null);
  const subscribeMany = useSubscribeMany();
  const [picked, setPicked] = useState<Set<string>>(new Set());

  function toggle(url: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  }

  function subscribePicked() {
    const inputs = STARTERS.filter((f) => picked.has(f.url)).map((f) => ({
      feed_url: f.url,
      title: f.title,
      folder_id: null,
    }));
    if (inputs.length > 0) subscribeMany.mutate(inputs);
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow picking the same file again after a failure
    if (!file) return;
    setError(null);
    try {
      await importer.mutateAsync(file);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't import that file.");
    }
  }

  return (
    <section className={styles.root} aria-label="Welcome">
      {isMobile && (
        <div className={styles.bar}>
          <button type="button" className={styles.menuBtn} aria-label="Open feeds" onClick={openSidebar}>
            <Menu size={20} />
          </button>
        </div>
      )}
      <div className={styles.body}>
        <h1 className={styles.title}>Welcome to Alo Reader</h1>
        <p className={styles.lead}>Bring the feeds you already follow, or start with one.</p>

        <div className={`${styles.option} ${styles.primary}`}>
          <h2 className={styles.optionTitle}>Bring your feeds from another reader</h2>
          <p className={styles.optionBody}>
            Every RSS reader can export your subscriptions as one OPML file. Import it here and
            your feeds and folders arrive in one step.
          </p>
          <label className={styles.btnPrimary} data-busy={importer.isPending || undefined}>
            {importer.isPending ? <Loader2 size={16} className={styles.spin} /> : <FileUp size={16} />}
            <span>{importer.isPending ? "Importing…" : "Import an OPML file"}</span>
            <input
              type="file"
              accept=".opml,.xml,application/xml,text/xml"
              className={styles.fileInput}
              onChange={(e) => void onFile(e)}
              disabled={importer.isPending}
            />
          </label>
          {hasPublicSite() && (
            <p className={styles.guides}>
              How to export it:{" "}
              <a href="/from/feedly" target="_blank" rel="noopener">
                from Feedly
              </a>
              ,{" "}
              <a href="/from/inoreader" target="_blank" rel="noopener">
                from Inoreader
              </a>
              .
            </p>
          )}
          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}
        </div>

        <div className={styles.option}>
          <h2 className={styles.optionTitle}>Add a feed or a site</h2>
          <p className={styles.optionBody}>
            Paste a site&rsquo;s address and Alo Reader finds its feed, or paste the feed itself.
          </p>
          <button type="button" className={styles.btnSecondary} onClick={openAddFeed}>
            <Plus size={16} />
            <span>Add a feed</span>
          </button>
        </div>

        <div className={styles.starters}>
          <h2 className={styles.optionTitle}>New to RSS? Start with a few</h2>
          <p className={styles.optionBody}>
            Tick the ones you like. You can unsubscribe from any of them later.
          </p>
          <ul className={styles.starterList}>
            {STARTERS.map((f) => (
              <li key={f.url}>
                <label className={styles.starter}>
                  <input
                    type="checkbox"
                    checked={picked.has(f.url)}
                    onChange={() => toggle(f.url)}
                    disabled={subscribeMany.isPending}
                  />
                  <span className={styles.starterText}>
                    <span className={styles.starterTitle}>{f.title}</span>
                    <span className={styles.starterAbout}>{f.about}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          {/* Quiet until something is ticked; then it is the next thing to press. */}
          <button
            type="button"
            className={picked.size > 0 ? styles.btnPrimary : styles.btnSecondary}
            onClick={subscribePicked}
            disabled={picked.size === 0 || subscribeMany.isPending}
          >
            {subscribeMany.isPending ? <Loader2 size={16} className={styles.spin} /> : <Plus size={16} />}
            <span>
              {subscribeMany.isPending
                ? "Subscribing…"
                : picked.size === 0
                  ? "Subscribe to ticked feeds" // not bare "Subscribe": the sidebar's button has that name
                  : `Subscribe to ${picked.size} feed${picked.size === 1 ? "" : "s"}`}
            </span>
          </button>
        </div>
      </div>
    </section>
  );
}
