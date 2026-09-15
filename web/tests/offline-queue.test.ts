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
    await q.replayQueue(async (item) => {
      sent.push(item.ids);
    });
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

describe("poison items", () => {
  it("drops an item the server rejects and keeps draining", async () => {
    // A 4xx is the server's final answer — an entry unsubscribed while we were
    // offline, say. Retrying it forever parks it at the head of the queue and blocks
    // every change behind it, on every reconnect, permanently.
    const q = await import("../src/app/offline/queue");
    const { ApiError } = await import("../src/api/client");
    await q.enqueue({ ids: [1], read: true, changed_at: "t1" });
    await q.enqueue({ ids: [2], read: true, changed_at: "t2" });
    await q.enqueue({ ids: [3], read: true, changed_at: "t3" });

    const sent: number[][] = [];
    const dropped = await q.replayQueue(async (item) => {
      sent.push(item.ids);
      if (item.ids[0] === 2) throw new ApiError(404, "not_found", "entry not found");
    });

    expect(sent).toEqual([[1], [2], [3]]); // item 3 was not blocked by item 2
    expect(dropped).toBe(1);
    expect(q.getQueuedCount()).toBe(0);
  });

  it("still stops at a transport failure so nothing is lost", async () => {
    const q = await import("../src/app/offline/queue");
    await q.enqueue({ ids: [1], read: true, changed_at: "t1" });
    await q.enqueue({ ids: [2], read: true, changed_at: "t2" });

    const dropped = await q.replayQueue(async (item) => {
      if (item.ids[0] === 2) throw new TypeError("Failed to fetch");
    });

    expect(dropped).toBe(0);
    expect(q.getQueuedCount()).toBe(1); // retried on the next reconnect
  });
});
