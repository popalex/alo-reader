// What a signed-out visitor sees at /app: reached from the landing page, or from a
// bookmark after the session ended. It speaks the landing page's visual language
// (same mark, wordmark, footer and tokens) so the two read as one product, and it
// carries the theme toggle and the legal links the bare Clerk form had none of.
//
// The form is Clerk's <SignIn>, passed in as children; ClerkApp sets it up so that
// creating an account happens right here rather than on Clerk's hosted page.

import type { ReactNode } from "react";

import { ThemeToggle } from "./ThemeToggle";
import styles from "./SignedOutShell.module.css";

function Mark({ className }: { className: string }) {
  return (
    <span className={className} aria-hidden="true">
      <svg viewBox="0 0 24 24">
        <path d="M4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16" />
        <circle cx="5" cy="19" r="1.6" fill="currentColor" stroke="none" />
      </svg>
    </span>
  );
}

export function SignedOutShell({ children }: { children: ReactNode }) {
  return (
    <div className={styles.page}>
      <header className={styles.nav}>
        <a className={styles.brand} href="/">
          <Mark className={styles.markSmall} />
          alo reader
        </a>
        <ThemeToggle />
      </header>

      <main className={styles.main}>
        <Mark className={styles.markLarge} />
        <h1 className={styles.title}>Sign in or create an account</h1>
        <p className={styles.lede}>
          Every article from every feed you follow, in the order it was published.
        </p>
        <div className={styles.form}>{children}</div>
      </main>

      <footer className={styles.footer}>
        <span>© 2026 alo reader</span>
        <span className={styles.sep} />
        <a href="https://github.com/popalex/alo-reader">Source (AGPL-3.0)</a>
        <a href="/legal">Terms &amp; privacy</a>
      </footer>
    </div>
  );
}
