// The entry list's top bar: mobile hamburger, stream title, and the actions
// (refresh, mark-all-read, density). On desktop the actions are inline;
// on mobile they collapse into a lazy-loaded overflow menu.

import { type ComponentProps, useEffect, useState } from "react";

import { CheckCheck, Loader2, Menu, MoreVertical, RefreshCw } from "lucide-react";

import { pushToast } from "../../app/toast";
import { DensityToggle } from "./DensityToggle";
import type { Density } from "./density";
import type { MobileActionsMenu as MenuComponent } from "./MobileActionsMenu";
import styles from "./EntryList.module.css";
import menuStyles from "./MobileActionsMenu.module.css";

// Mobile-only overflow menu. Its Radix dropdown code (~18 kB gz) never ships to
// desktop, and on mobile it loads on the first tap rather than at startup: rendering
// it eagerly put the chunk request and the dropdown's mount inside the first-load
// window, which is exactly what Lighthouse's mobile run measures. Until then the
// header shows a plain button that looks the same.
type Menu = typeof MenuComponent;
let loadedMenu: Menu | undefined;
let menuLoad: Promise<Menu> | undefined;
function loadMenu(): Promise<Menu> {
  menuLoad ??= import("./MobileActionsMenu").then(
    (m) => (loadedMenu = m.MobileActionsMenu),
    (error: unknown) => {
      menuLoad = undefined;
      throw error;
    },
  );
  return menuLoad;
}

function LazyMobileActionsMenu(
  props: Omit<ComponentProps<Menu>, "defaultOpen" | "focusFirstItem">,
) {
  const [MenuImpl, setMenuImpl] = useState<Menu | undefined>(() => loadedMenu);
  const [tapped, setTapped] = useState<false | "pointer" | "keyboard">(false);
  useEffect(() => {
    if (!tapped || MenuImpl) return;
    let live = true;
    loadMenu().then(
      (m) => live && setMenuImpl(() => m),
      () => {
        if (!live) return;
        pushToast("Couldn't open that. Reload the page to get the latest version of the app.");
        setTapped(false);
      },
    );
    return () => {
      live = false;
    };
  }, [tapped, MenuImpl]);

  if (MenuImpl) {
    return (
      <MenuImpl {...props} defaultOpen={tapped !== false} focusFirstItem={tapped === "keyboard"} />
    );
  }
  return (
    <button
      type="button"
      className={menuStyles.trigger}
      aria-label="More actions"
      aria-haspopup="menu"
      // A click fired by Enter or Space has detail 0.
      onClick={(event) => setTapped(event.detail === 0 ? "keyboard" : "pointer")}
    >
      <MoreVertical size={18} />
    </button>
  );
}

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
        </div>
        {isMobile && (
          <LazyMobileActionsMenu
            onRefresh={onRefresh}
            onMarkAllRead={onMarkAllRead}
            canMarkAllRead={canMarkAll && !markPending}
          />
        )}
      </div>
    </header>
  );
}
