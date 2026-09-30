import { describe, expect, it } from "vitest";

import { adjacentEntry } from "../src/features/stream/selection";

const order = [
  { id: 10, title: "First", is_read: false },
  { id: 20, title: "Second", is_read: true },
  { id: 30, title: "Third", is_read: false },
];

describe("adjacentEntry", () => {
  it("finds the next and the previous row in display order", () => {
    expect(adjacentEntry(order, 20, 1)?.id).toBe(30);
    expect(adjacentEntry(order, 20, -1)?.id).toBe(10);
  });

  it("returns null past either end, for nothing open, and for an id not in the list", () => {
    expect(adjacentEntry(order, 30, 1)).toBeNull();
    expect(adjacentEntry(order, 10, -1)).toBeNull();
    expect(adjacentEntry(order, null, 1)).toBeNull();
    expect(adjacentEntry(order, 99, 1)).toBeNull();
  });
});
