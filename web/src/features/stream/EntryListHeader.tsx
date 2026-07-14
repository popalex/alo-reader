// The entry list's top bar: mobile hamburger, stream title, and the actions
// (refresh, mark-all-read, density, theme). On desktop the actions are inline;
// on mobile they collapse into a lazy-loaded overflow menu.

import { Suspense, lazy } from "react";

import { CheckCheck, Loader2, Menu, RefreshCw } from "lucide-react";

import { ThemeToggle } from "../../app/ThemeToggle";
import { DensityToggle } from "./DensityToggle";
import type { Density } from "./density";
import styles from "./EntryList.module.css";

// Mobile-only overflow menu — lazy so its Radix dropdown code (~18kB gz) never
// ships to desktop, where the inline controls are used instead.
const MobileActionsMenu = lazy(() =>
  import("./MobileActionsMenu").then((m) => ({ default: m.MobileActionsMenu })),
);

export function EntryListHeader({
  title,
  density,
  setDensity,
  online,
  searching,
  markPending,
  hasEntries,
  isMobile,
  onOpenSidebar,
  onRefresh,
  onMarkAllRead,
}: {
  title: string;
  density: Density;
  setDensity: (d: Density) => void;
  online: boolean;
  searching: boolean;
  markPending: boolean;
  hasEntries: boolean;
  isMobile: boolean;
  onOpenSidebar: () => void;
  onRefresh: () => void;
  onMarkAllRead: () => void;
}) {
  // Mark-all marks the whole base stream, so it's ambiguous while a search filters
  // the view, can't be queued offline, and needs something to mark.
  const canMarkAll = online && !searching && hasEntries;
  return (
    <header className={styles.head}>
      <button type="button" className={styles.menuBtn} aria-label="Open feeds" onClick={onOpenSidebar}>
        <Menu size={19} />
      </button>
      <h1 className={styles.title}>{title}</h1>
      <div className={styles.controls}>
        {/* Desktop: inline controls. Mobile: collapsed into the overflow menu. */}
        <div className={styles.desktopActions}>
          <button
            type="button"
            className={styles.toolBtn}
            title="Refresh"
            aria-label="Refresh"
            onClick={onRefresh}
          >
            <RefreshCw size={15} />
          </button>
          <button
            type="button"
            className={styles.toolBtn}
            title={
              markPending
                ? "Marking all read…"
                : searching
                  ? "Mark all read (clear search first)"
                  : online
                    ? "Mark all read"
                    : "Mark all read (unavailable offline)"
            }
            aria-label="Mark all read"
            aria-busy={markPending || undefined}
            onClick={onMarkAllRead}
            disabled={!canMarkAll || markPending}
          >
            {markPending ? (
              <Loader2 size={15} className={styles.spin} />
            ) : (
              <CheckCheck size={15} />
            )}
          </button>
          <span className={styles.sep} />
          <DensityToggle value={density} onChange={setDensity} />
          <ThemeToggle />
        </div>
        {isMobile && (
          <Suspense fallback={null}>
            <MobileActionsMenu
              onRefresh={onRefresh}
              onMarkAllRead={onMarkAllRead}
              canMarkAllRead={canMarkAll}
            />
          </Suspense>
        )}
      </div>
    </header>
  );
}
