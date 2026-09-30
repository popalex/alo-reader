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
import { useImportOpml } from "../../api/feedMutations";
import { hasPublicSite } from "../../app/instance";
import { useIsMobile } from "../../lib/useMediaQuery";
import { useMobileNav } from "../layout/mobileNav";
import styles from "./Welcome.module.css";

export function Welcome({ onAddFeed }: { onAddFeed: () => void }) {
  const isMobile = useIsMobile();
  const { openSidebar } = useMobileNav();
  const importer = useImportOpml();
  const [error, setError] = useState<string | null>(null);

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
        <h1 className={styles.title}>Welcome to alo reader</h1>
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
            Paste a site&rsquo;s address and alo reader finds its feed, or paste the feed itself.
          </p>
          <button type="button" className={styles.btnSecondary} onClick={onAddFeed}>
            <Plus size={16} />
            <span>Add a feed</span>
          </button>
        </div>
      </div>
    </section>
  );
}
