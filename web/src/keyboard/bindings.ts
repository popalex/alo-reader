// The keyboard map — the single source of truth for WP-12. Both the global
// handler (useKeyboard) and the `?` help overlay are generated from this table,
// so a binding can never drift from its documentation (a unit test asserts the
// overlay lists exactly these). The keymap is fixed by the WP-12 brief; add
// nothing here without updating that brief.
//
// A binding has one or more `combos`. Each combo is a key *sequence*: a single
// key like ["j"], an alternative like ["o"] / ["Enter"] (two combos), or a
// `g`-prefixed chord like ["g", "a"]. Keys are compared against KeyboardEvent
// .key values, so "A" means Shift+a and "?" means Shift+/.

export type BindingId =
  | "next"
  | "prev"
  | "open"
  | "openOriginal"
  | "toggleRead"
  | "star"
  | "markAllRead"
  | "refresh"
  | "goAll"
  | "goStarred"
  | "focusSearch"
  | "help";

export interface Binding {
  id: BindingId;
  /** Alternatives; each is a key sequence (length 2 ⇒ a chord). */
  combos: string[][];
  /** Human label shown in the help overlay. */
  label: string;
  /** Grouping heading in the help overlay, in table order. */
  group: string;
}

export const BINDINGS: Binding[] = [
  { id: "next", combos: [["j"]], label: "Next article", group: "Navigation" },
  { id: "prev", combos: [["k"]], label: "Previous article", group: "Navigation" },
  { id: "open", combos: [["o"], ["Enter"]], label: "Open or close article", group: "Navigation" },

  { id: "star", combos: [["s"]], label: "Star or unstar", group: "Article" },
  { id: "toggleRead", combos: [["m"]], label: "Toggle read / unread", group: "Article" },
  { id: "openOriginal", combos: [["v"]], label: "Open original in a new tab", group: "Article" },

  { id: "markAllRead", combos: [["A"]], label: "Mark all as read", group: "List" },
  { id: "refresh", combos: [["r"]], label: "Refresh", group: "List" },

  { id: "goAll", combos: [["g", "a"]], label: "Go to All items", group: "Go to" },
  { id: "goStarred", combos: [["g", "s"]], label: "Go to Starred", group: "Go to" },

  { id: "focusSearch", combos: [["/"]], label: "Search", group: "App" },
  { id: "help", combos: [["?"]], label: "Keyboard shortcuts", group: "App" },
];

/** First keys of every chord (e.g. "g") — pressed alone they open a chord window. */
export const CHORD_PREFIXES: ReadonlySet<string> = new Set(
  BINDINGS.flatMap((b) => b.combos).filter((c) => c.length === 2).map((c) => c[0]),
);

/** Resolve a plain (non-chord) key press to a binding id, or null. */
export function matchKey(key: string): BindingId | null {
  for (const b of BINDINGS)
    for (const combo of b.combos) if (combo.length === 1 && combo[0] === key) return b.id;
  return null;
}

/** Resolve the second key of a `prefix`-chord to a binding id, or null. */
export function matchChord(prefix: string, key: string): BindingId | null {
  for (const b of BINDINGS)
    for (const combo of b.combos)
      if (combo.length === 2 && combo[0] === prefix && combo[1] === key) return b.id;
  return null;
}

/** Group order preserved from the table, for the help overlay. */
export function groupedBindings(): Array<{ group: string; bindings: Binding[] }> {
  const order: string[] = [];
  const byGroup = new Map<string, Binding[]>();
  for (const b of BINDINGS) {
    if (!byGroup.has(b.group)) {
      byGroup.set(b.group, []);
      order.push(b.group);
    }
    byGroup.get(b.group)!.push(b);
  }
  return order.map((group) => ({ group, bindings: byGroup.get(group)! }));
}
