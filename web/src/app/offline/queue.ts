// The offline mutation outbox (WP-14). Read/star changes made while offline are
// persisted here (IndexedDB via idb, so they survive reload/close) and replayed
// through the normal POST /entries/state on reconnect. The endpoint is idempotent
// and last-writer-wins on changed_at (DESIGN §5), so replay order and duplicates
// are non-issues — the queue's job is just "don't lose it, send it once."

import { openDB, type DBSchema, type IDBPDatabase } from "idb";

export interface OutboxItem {
  id?: number; // auto-increment key (FIFO)
  ids: number[];
  read?: boolean;
  starred?: boolean;
  changed_at: string; // ISO, stamped when the user acted — preserved for LWW
}

interface AloDB extends DBSchema {
  outbox: { key: number; value: OutboxItem };
}

let dbPromise: Promise<IDBPDatabase<AloDB>> | null = null;
function db(): Promise<IDBPDatabase<AloDB>> {
  return (dbPromise ??= openDB<AloDB>("alo-offline", 1, {
    upgrade(d) {
      d.createObjectStore("outbox", { keyPath: "id", autoIncrement: true });
    },
  }));
}

// Small external store so the queued-count badge can subscribe without a hook.
const listeners = new Set<() => void>();
let count = 0;

function notify(): void {
  for (const l of listeners) l();
}

export function subscribeQueue(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function getQueuedCount(): number {
  return count;
}

/** Recompute the badge count from storage (call on load and after each change). */
export async function refreshQueuedCount(): Promise<void> {
  count = await (await db()).count("outbox");
  notify();
}

export async function enqueue(item: OutboxItem): Promise<void> {
  await (await db()).add("outbox", item);
  await refreshQueuedCount();
}

let replaying = false;

/** Drain the outbox through `post`, oldest-first, single-flight. Each item is
 *  removed only after a successful send (so failures retry, and nothing sends
 *  twice). Stops at the first failure — the next `online`/load tries again. */
export async function replayQueue(post: (item: OutboxItem) => Promise<void>): Promise<void> {
  if (replaying || !navigator.onLine) return;
  replaying = true;
  try {
    const d = await db();
    for (const item of await d.getAll("outbox")) {
      try {
        await post(item);
      } catch {
        break; // offline again / server error → leave it queued, retry later
      }
      if (item.id !== undefined) await d.delete("outbox", item.id);
      await refreshQueuedCount();
    }
  } finally {
    replaying = false;
  }
}
