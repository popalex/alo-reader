// The toast surface: subscribes to the toast store (toast.ts) and renders it.
// Accessible tones map to aria roles (error → alert, info → status). Styling via
// tokens keeps it themed.

import { useSyncExternalStore } from "react";

import { X } from "lucide-react";

import { dismissToast, snapshot, subscribe } from "./toast";
import styles from "./toast.module.css";

export function Toaster() {
  const items = useSyncExternalStore(subscribe, snapshot, snapshot);
  if (items.length === 0) return null;
  return (
    <div className={styles.viewport}>
      {items.map((t) => (
        <div
          key={t.id}
          className={styles.toast}
          data-tone={t.tone}
          role={t.tone === "error" ? "alert" : "status"}
        >
          <span className={styles.message}>{t.message}</span>
          <button
            type="button"
            className={styles.close}
            aria-label="Dismiss"
            onClick={() => dismissToast(t.id)}
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
