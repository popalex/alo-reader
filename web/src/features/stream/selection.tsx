// The current stream's selected entry. A single useReducer store (per DESIGN's
// note that the keyboard WP will drive it) exposed via context so the list sets
// it and the reading pane reads it. Reset per stream by keying the provider.

import { createContext, useContext, useMemo, useReducer, type ReactNode } from "react";

interface SelectionState {
  selectedId: number | null;
}

type Action = { type: "select"; id: number } | { type: "clear" };

function reducer(state: SelectionState, action: Action): SelectionState {
  switch (action.type) {
    case "select":
      return state.selectedId === action.id ? state : { selectedId: action.id };
    case "clear":
      return state.selectedId === null ? state : { selectedId: null };
  }
}

interface SelectionApi extends SelectionState {
  select: (id: number) => void;
  clear: () => void;
}

const SelectionContext = createContext<SelectionApi | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, { selectedId: null });
  const api = useMemo<SelectionApi>(
    () => ({
      selectedId: state.selectedId,
      select: (id) => dispatch({ type: "select", id }),
      clear: () => dispatch({ type: "clear" }),
    }),
    [state.selectedId],
  );
  return <SelectionContext.Provider value={api}>{children}</SelectionContext.Provider>;
}

export function useSelection(): SelectionApi {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error("useSelection must be used within a SelectionProvider");
  return ctx;
}
