// Mounts the replay driver and shows offline/sync status with the queued-count
// badge (WP-14). Rendered once inside the app providers. Silent when online with
// an empty queue.

import { RefreshCw, WifiOff } from "lucide-react";

import { useOfflineReplay, useOnline, useQueuedCount } from "./useOffline";
import styles from "./OfflineManager.module.css";

export function OfflineManager() {
  useOfflineReplay();
  const online = useOnline();
  const queued = useQueuedCount();

  if (online && queued === 0) return null;

  return (
    <div className={styles.bar} role="status" aria-live="polite" data-testid="offline-bar">
      {online ? (
        <RefreshCw size={14} className={styles.spin} aria-hidden="true" />
      ) : (
        <WifiOff size={14} aria-hidden="true" />
      )}
      <span>
        {online ? "Syncing" : "Offline"}
        {queued > 0 ? (
          <>
            {" — "}
            <b data-testid="queued-count">{queued}</b> {queued === 1 ? "change" : "changes"} queued
          </>
        ) : (
          " — changes will sync when you reconnect"
        )}
      </span>
    </div>
  );
}
