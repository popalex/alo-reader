// Provides the per-stream selection store (selection.ts) to the list + reader.
// Split from the store/hook so this file only exports a component (HMR-safe).

import { useMemo, useReducer, useState, type ReactNode } from "react";

import {
  SelectionContext,
  selectionReducer,
  type ReadingOrderItem,
  type SelectionApi,
} from "./selection";

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(selectionReducer, { cursorId: null, openId: null });
  const [readingOrder, setReadingOrder] = useState<readonly ReadingOrderItem[]>([]);
  const api = useMemo<SelectionApi>(
    () => ({
      cursorId: state.cursorId,
      openId: state.openId,
      setCursor: (id) => dispatch({ type: "cursor", id }),
      open: (id) => dispatch({ type: "open", id }),
      close: () => dispatch({ type: "close" }),
      clear: () => dispatch({ type: "clear" }),
      readingOrder,
      setReadingOrder,
    }),
    [state.cursorId, state.openId, readingOrder],
  );
  return <SelectionContext.Provider value={api}>{children}</SelectionContext.Provider>;
}
