// The current stream's selection store (no JSX — the provider component lives in
// SelectionProvider.tsx). Selection is split into two ideas the keyboard model
// (WP-12) needs to keep apart:
//   - cursorId: the keyboard-highlighted row (j/k move it, visible ring). Does
//     not open or mark anything.
//   - openId:   the row shown in the reading pane (o/Enter/click open it, which
//     marks it read). Moving the cursor never changes what's open.
// A mouse click sets both. Reset per stream by keying the provider (StreamView).

import { createContext, useContext } from "react";

export interface SelectionState {
  cursorId: number | null;
  openId: number | null;
}

export type SelectionAction =
  | { type: "cursor"; id: number } // move the keyboard cursor only
  | { type: "open"; id: number } // open in the reader (cursor follows)
  | { type: "close" } // close the reader, keep the cursor
  | { type: "clear" }; // reset both

export function selectionReducer(state: SelectionState, action: SelectionAction): SelectionState {
  switch (action.type) {
    case "cursor":
      return state.cursorId === action.id ? state : { ...state, cursorId: action.id };
    case "open":
      return state.openId === action.id && state.cursorId === action.id
        ? state
        : { cursorId: action.id, openId: action.id };
    case "close":
      return state.openId === null ? state : { ...state, openId: null };
    case "clear":
      return state.cursorId === null && state.openId === null
        ? state
        : { cursorId: null, openId: null };
  }
}

/** One row of the list as the reader needs it to offer the next article: the list
 *  publishes these in display order (search results included), so "next" means the
 *  row below in what the reader sees, not in some other query. */
export interface ReadingOrderItem {
  id: number;
  title: string;
  is_read: boolean;
}

/** The row `delta` places away from `id` in the reading order, or null at either end
 *  (or when `id` is not in it). */
export function adjacentEntry(
  order: readonly ReadingOrderItem[],
  id: number | null,
  delta: 1 | -1,
): ReadingOrderItem | null {
  if (id == null) return null;
  const i = order.findIndex((e) => e.id === id);
  if (i < 0) return null;
  return order[i + delta] ?? null;
}

export interface SelectionApi extends SelectionState {
  setCursor: (id: number) => void;
  open: (id: number) => void;
  close: () => void;
  clear: () => void;
  /** The list's rows in display order, for the reader's next/previous. */
  readingOrder: readonly ReadingOrderItem[];
  setReadingOrder: (order: readonly ReadingOrderItem[]) => void;
}

export const SelectionContext = createContext<SelectionApi | null>(null);

export function useSelection(): SelectionApi {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error("useSelection must be used within a SelectionProvider");
  return ctx;
}
