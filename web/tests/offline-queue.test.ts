import { IDBFactory } from "fake-indexeddb";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Reset the DB and the queue module's cached state before each test.
beforeEach(() => {
  vi.resetModules();
  globalThis.indexedDB = new IDBFactory();
});

describe("offline queue", () => {
  it("replays FIFO and exactly once, then drains", async () => {
    const q = await import("../src/app/offline/queue");
    await q.enqueue({ ids: [1], read: true, changed_at: "t1" });
    await q.enqueue({ ids: [2], starred: true, changed_at: "t2" });
    expect(q.getQueuedCount()).toBe(2);

    const sent: number[][] = [];
    await q.replayQueue(async (item) => {
      sent.push(item.ids);
    });
    expect(sent).toEqual([[1], [2]]); // oldest-first
    expect(q.getQueuedCount()).toBe(0);

    // A second replay sends nothing — each item left exactly once.
    await q.replayQueue(async (item) => sent.push(item.ids));
    expect(sent).toEqual([[1], [2]]);
  });

  it("stops at the first failure and retries later without loss or duplication", async () => {
    const q = await import("../src/app/offline/queue");
    await q.enqueue({ ids: [1], read: true, changed_at: "t1" });
    await q.enqueue({ ids: [2], read: true, changed_at: "t2" });

    // First send succeeds; the second fails (still offline) → stop, keep item 2.
    await q.replayQueue(async (item) => {
      if (item.ids[0] === 2) throw new Error("network");
    });
    expect(q.getQueuedCount()).toBe(1);

    // Reconnect: the retained item replays once.
    const sent: number[][] = [];
    await q.replayQueue(async (item) => {
      sent.push(item.ids);
    });
    expect(sent).toEqual([[2]]);
    expect(q.getQueuedCount()).toBe(0);
  });

  it("preserves the original changed_at for LWW replay", async () => {
    const q = await import("../src/app/offline/queue");
    await q.enqueue({ ids: [7], read: true, changed_at: "2026-01-01T10:00:00.000Z" });
    const seen: string[] = [];
    await q.replayQueue(async (item) => {
      seen.push(item.changed_at);
    });
    expect(seen).toEqual(["2026-01-01T10:00:00.000Z"]);
  });
});
