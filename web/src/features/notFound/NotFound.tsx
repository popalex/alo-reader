// What the app shows for an /app/... address no route matches, in place of the
// article list. The public site has its own 404 (deploy/landing/error.html); this
// is the signed-in version, so it points back to the reader, not the front page.

import { Link } from "@tanstack/react-router";
import { Rss } from "lucide-react";

import styles from "./NotFound.module.css";

export function NotFound() {
  return (
    <section className={styles.root} aria-label="Page not found">
      <div className={styles.mark} aria-hidden="true">
        <Rss size={30} strokeWidth={1.6} />
      </div>
      <h1 className={styles.title}>Nothing here.</h1>
      <p className={styles.body}>
        This address has no page in Alo Reader. The link may be old, or it has a typo in it.
      </p>
      <Link to="/" className={styles.action}>
        Go to All items
      </Link>
    </section>
  );
}
