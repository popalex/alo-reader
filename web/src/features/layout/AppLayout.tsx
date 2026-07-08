// The persistent three-pane shell: sidebar + routed content (list + reader).
// Rendered by the router's root route; child routes fill the <Outlet/>.

import { Outlet } from "@tanstack/react-router";

import { UnreadAnnouncer } from "../../app/UnreadAnnouncer";
import { Sidebar } from "../sidebar/Sidebar";
import styles from "./AppLayout.module.css";

export function AppLayout() {
  return (
    <div className={styles.shell}>
      <Sidebar />
      <div className={styles.content}>
        <Outlet />
      </div>
      <UnreadAnnouncer />
    </div>
  );
}
