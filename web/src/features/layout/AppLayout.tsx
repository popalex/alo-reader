// The persistent three-pane shell: sidebar + routed content (list + reader). On
// desktop the sidebar is a fixed rail; on mobile it collapses into an off-canvas
// drawer opened from the list's top-bar hamburger (see MobileNavContext), and the
// content pane gets the full screen.

import { useEffect, useState } from "react";

import { Outlet, useRouterState } from "@tanstack/react-router";

import { UnreadAnnouncer } from "../../app/UnreadAnnouncer";
import { useIsMobile } from "../../lib/useMediaQuery";
import { Sidebar } from "../sidebar/Sidebar";
import { MobileSidebar } from "./MobileSidebar";
import { MobileNavContext } from "./mobileNav";
import styles from "./AppLayout.module.css";

export function AppLayout() {
  const isMobile = useIsMobile();
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Close the drawer whenever the stream changes (tapping a feed navigates).
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  useEffect(() => setDrawerOpen(false), [pathname]);

  return (
    <MobileNavContext.Provider value={{ openSidebar: () => setDrawerOpen(true) }}>
      <div className={styles.shell}>
        {!isMobile && <Sidebar />}
        <div className={styles.content}>
          <Outlet />
        </div>
        <UnreadAnnouncer />
      </div>
      {isMobile && <MobileSidebar open={drawerOpen} onOpenChange={setDrawerOpen} />}
    </MobileNavContext.Provider>
  );
}
