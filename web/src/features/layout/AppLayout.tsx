// The persistent three-pane shell: sidebar + routed content (list + reader). On
// desktop the sidebar is a fixed rail; on mobile it collapses into an off-canvas
// drawer opened from the list's top-bar hamburger (see MobileNavContext), and the
// content pane gets the full screen.

import { useEffect, useState } from "react";

import { Outlet, useRouterState } from "@tanstack/react-router";

import { usePendingFeedPolling } from "../../api/queries";
import { UnreadAnnouncer } from "../../app/UnreadAnnouncer";
import { ErrorBoundary } from "../../components/ErrorBoundary";
import { useIsMobile } from "../../lib/useMediaQuery";
import { Sidebar } from "../sidebar/Sidebar";
import { MobileSidebar } from "./MobileSidebar";
import { MobileNavContext } from "./mobileNav";
import styles from "./AppLayout.module.css";

export function AppLayout() {
  const isMobile = useIsMobile();
  const [drawerOpen, setDrawerOpen] = useState(false);
  usePendingFeedPolling(); // auto-refresh a just-added feed until the worker fills it in

  // Close the drawer whenever the stream changes (tapping a feed navigates).
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  useEffect(() => setDrawerOpen(false), [pathname]);

  return (
    <MobileNavContext.Provider value={{ openSidebar: () => setDrawerOpen(true) }}>
      <div className={styles.shell}>
        {!isMobile && <Sidebar />}
        <div className={styles.content}>
          {/* A render error in one stream shouldn't blank the whole app; reset on
              navigation so moving to another view recovers. */}
          <ErrorBoundary
            resetKey={pathname}
            fallback={
              <div className={styles.crash} role="alert">
                <p className={styles.crashTitle}>Something went wrong</p>
                <p>This view ran into an error. Try reloading the page.</p>
                <button
                  type="button"
                  className={styles.crashBtn}
                  onClick={() => window.location.reload()}
                >
                  Reload
                </button>
              </div>
            }
          >
            <Outlet />
          </ErrorBoundary>
        </div>
        <UnreadAnnouncer />
      </div>
      {isMobile && <MobileSidebar open={drawerOpen} onOpenChange={setDrawerOpen} />}
    </MobileNavContext.Provider>
  );
}
