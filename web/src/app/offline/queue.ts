// The offline mutation outbox (WP-14). Read/star changes made while offline are
// persisted here (IndexedDB via idb, so they survive reload/close) and replayed
// through the normal POST /entries/state on reconnect. The endpoint is idempotent
// and last-writer-wins on changed_at (DESIGN §5), so replay order and duplicates
// are non-issues — the queue's job is just "don't lose it, send it once."

import { ApiError } from "../../api/client";
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
 *  removed only after the server has taken it (so nothing sends twice).
 *
 *  Returns how many items were dropped as unsendable. A transport failure stops the
 *  drain and leaves everything queued for the next `online`/load, but a 4xx is the
 *  server's final answer — an entry deleted while we were offline, say — and retrying
 *  it forever would park it at the head of the queue and block every change behind it
 *  on every reconnect, permanently. */
export async function replayQueue(post: (item: OutboxItem) => Promise<void>): Promise<number> {
  if (replaying || !navigator.onLine) return 0;
  replaying = true;
  let dropped = 0;
  try {
    const d = await db();
    for (const item of await d.getAll("outbox")) {
      try {
        await post(item);
      } catch (err) {
        const permanent = err instanceof ApiError && err.status >= 400 && err.status < 500;
        if (!permanent) break; // offline again / server error → retry later
        dropped += 1;
      }
      if (item.id !== undefined) await d.delete("outbox", item.id);
      await refreshQueuedCount();
    }
  } finally {
    replaying = false;
  }
  return dropped;
}
