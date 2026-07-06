// Minimal accessible toast surface. Query/mutation errors push here via the
// QueryClient's cache handler; the tokens keep it themed. Hand-rolled (no dep)
// because it's small and product-shaped — an external store so non-React code
// (the QueryCache) can push without a hook.

import { useSyncExternalStore } from "react";

import { X } from "lucide-react";

import styles from "./toast.module.css";

export type ToastTone = "error" | "info";
export interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
}

const DISMISS_MS = 6000;

let toasts: Toast[] = [];
const listeners = new Set<() => void>();
let nextId = 1;

function emit(): void {
  for (const l of listeners) l();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

function snapshot(): Toast[] {
  return toasts;
}

export function pushToast(message: string, tone: ToastTone = "error"): number {
  const id = nextId++;
  toasts = [...toasts, { id, message, tone }];
  emit();
  window.setTimeout(() => dismissToast(id), DISMISS_MS);
  return id;
}

export function dismissToast(id: number): void {
  const next = toasts.filter((t) => t.id !== id);
  if (next.length !== toasts.length) {
    toasts = next;
    emit();
  }
}

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
