// Colour-theme store. The tokens in styles/tokens.css react to the `data-theme`
// attribute on <html> (with a prefers-color-scheme fallback when it's absent),
// so this module's only job is to own the user's choice, persist it, and mirror
// it onto that attribute. No React context needed — a tiny external store keeps
// it available to initTheme() (called before render) and to useTheme().

import { useSyncExternalStore } from "react";

export type ThemeChoice = "light" | "dark" | "system";

const STORAGE_KEY = "alo-theme";
const listeners = new Set<() => void>();

function read(): ThemeChoice {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* localStorage unavailable (private mode, SSR) — fall through to default */
  }
  return "system";
}

let choice: ThemeChoice = read();

function applyToDocument(c: ThemeChoice): void {
  const root = document.documentElement;
  // "system" means: no explicit attribute, let prefers-color-scheme decide.
  if (c === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", c);
}

/** Apply the stored choice to the document. Call once before first render. */
export function initTheme(): void {
  applyToDocument(choice);
}

export function getTheme(): ThemeChoice {
  return choice;
}

export function setTheme(next: ThemeChoice): void {
  choice = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* ignore persistence failures — the in-memory choice still applies */
  }
  applyToDocument(next);
  for (const l of listeners) l();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function useTheme(): readonly [ThemeChoice, (next: ThemeChoice) => void] {
  const value = useSyncExternalStore(subscribe, getTheme, getTheme);
  return [value, setTheme] as const;
}
